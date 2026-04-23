"""Dedup: model-based primary, deterministic Jaccard+bigram fallback.

Model dedup uses the cheapest available non-reasoning model per provider.
Deterministic fallback is category-aware: findings only merge within the same
category bucket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from . import prompts
from .providers import (
    ProviderResult,
    call_with_retry,
    parse_and_validate_findings,
)
from .types import (
    Category,
    Finding,
    ModelConfig,
    Severity,
    SEVERITY_RANK,
    normalize_category,
    normalize_severity,
)


log = logging.getLogger("dvad_agent.dedup")

STOP_WORDS = {
    "a", "an", "the", "is", "in", "on", "of", "and", "or", "to", "for", "by",
}


@dataclass
class DedupInput:
    reviewer: str
    severity: str
    category: str
    issue: str
    detail: str


@dataclass
class DedupResult:
    findings: list[Finding]
    method: str  # "model" | "deterministic"
    skipped: bool
    cost_usd: float
    input_tokens: int
    output_tokens: int


# ─── Deterministic fallback ───────────────────────────────────────────────────


def _tokens(text: str) -> list[str]:
    import re

    raw = re.split(r"\W+", text.lower())
    return [t for t in raw if t and t not in STOP_WORDS]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:])) if len(tokens) >= 2 else set()


def _prefix_match(a: list[str], b: list[str], n: int = 6) -> bool:
    return len(a) >= n and len(b) >= n and a[:n] == b[:n]


def deterministic_dedup(items: list[DedupInput]) -> list[Finding]:
    """Category-aware Jaccard 0.7 + bigram 0.3 merge rule."""
    # Bucket by category first.
    buckets: dict[str, list[DedupInput]] = {}
    for item in items:
        buckets.setdefault(item.category, []).append(item)

    groups: list[list[DedupInput]] = []
    for cat_items in buckets.values():
        precomputed: list[tuple[list[str], set[str], set[tuple[str, str]]]] = []
        for it in cat_items:
            toks = _tokens(it.issue)
            precomputed.append((toks, set(toks), _bigrams(toks)))

        assigned = [False] * len(cat_items)
        for i, it in enumerate(cat_items):
            if assigned[i]:
                continue
            cluster = [it]
            assigned[i] = True
            toks_i, set_i, bi_i = precomputed[i]
            for j in range(i + 1, len(cat_items)):
                if assigned[j]:
                    continue
                toks_j, set_j, bi_j = precomputed[j]
                jac_uni = _jaccard(set_i, set_j)
                jac_bi = _jaccard(bi_i, bi_j)
                if (jac_uni >= 0.7 and jac_bi >= 0.3) or _prefix_match(toks_i, toks_j):
                    cluster.append(cat_items[j])
                    assigned[j] = True
            groups.append(cluster)

    return [_merge_cluster(cluster) for cluster in groups]


def _merge_cluster(cluster: list[DedupInput]) -> Finding:
    # Severity = max
    max_sev = Severity.INFO
    for item in cluster:
        s = normalize_severity(item.severity)
        if SEVERITY_RANK[s] > SEVERITY_RANK[max_sev]:
            max_sev = s

    # Category = modal; tie-break by highest-severity contributor
    cat_counts: dict[str, int] = {}
    for item in cluster:
        cat_counts[item.category] = cat_counts.get(item.category, 0) + 1
    max_count = max(cat_counts.values())
    tied = [c for c, n in cat_counts.items() if n == max_count]
    if len(tied) == 1:
        cat_raw = tied[0]
    else:
        highest = cluster[0]
        highest_rank = SEVERITY_RANK[normalize_severity(highest.severity)]
        for item in cluster:
            rank = SEVERITY_RANK[normalize_severity(item.severity)]
            if rank > highest_rank:
                highest = item
                highest_rank = rank
        cat_raw = highest.category
    cat, cat_detail = normalize_category(cat_raw)

    models_reporting = sorted({item.reviewer for item in cluster})
    issues = sorted({item.issue for item in cluster}, key=len)
    issue = issues[0] if issues else cluster[0].issue
    details = [item.detail for item in cluster if item.detail]
    detail = " | ".join(dict.fromkeys(details))[:2000]

    return Finding(
        severity=max_sev,
        consensus=len(models_reporting),
        category=cat,
        issue=issue,
        detail=detail,
        category_detail=cat_detail,
        models_reporting=models_reporting,
    )


# ─── Model-based primary ──────────────────────────────────────────────────────


async def model_dedup(
    client: httpx.AsyncClient,
    items: list[DedupInput],
    model: ModelConfig,
    timeout_seconds: float,
) -> tuple[list[Finding] | None, ProviderResult | None]:
    """Returns (findings, usage) on success; (None, None) on any failure."""
    raw_findings = [
        {
            "reviewer": it.reviewer,
            "severity": it.severity,
            "category": it.category,
            "issue": it.issue,
            "detail": it.detail,
        }
        for it in items
    ]
    user_prompt = prompts.build_dedup_user_prompt(raw_findings)

    import asyncio

    try:
        async with asyncio.timeout(timeout_seconds):
            result = await call_with_retry(
                client, model, prompts.DEDUP_SYSTEM, user_prompt,
                max_output_tokens=model.max_output_tokens,
            )
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        log.warning("Model dedup failed (%s): %s", model.name, exc)
        return None, None

    parsed, err = parse_and_validate_findings(result.text, model.name, model.provider)
    if parsed is None or err is not None:
        log.warning("Model dedup response invalid (%s): %s", model.name, err.message if err else "?")
        return None, None

    findings: list[Finding] = []
    for f in parsed:
        source_indices = []
        # Best-effort: re-read from parsed raw
        # (we dropped source_indices in parse_and_validate_findings; reparse here)
    # Re-parse raw to recover source_indices if present.
    import json
    from .providers import sanitize_json_output

    cleaned = sanitize_json_output(result.text)
    try:
        raw = json.loads(cleaned)
    except Exception:  # noqa: BLE001
        raw = {"findings": []}
    for entry in raw.get("findings", []):
        severity = normalize_severity(entry.get("severity"))
        cat, cat_detail = normalize_category(entry.get("category"))
        issue = str(entry.get("issue", "")).strip()
        detail = str(entry.get("detail", "")).strip()
        if not issue:
            continue
        source_indices = entry.get("source_indices") or []
        models_reporting: list[str] = []
        for idx in source_indices:
            if isinstance(idx, int) and 0 <= idx < len(items):
                models_reporting.append(items[idx].reviewer)
        models_reporting = sorted(set(models_reporting))
        if not models_reporting:
            # Fallback: credit all contributors sharing the same issue token
            models_reporting = sorted({
                it.reviewer for it in items
                if _share_issue(it.issue, issue)
            }) or sorted({it.reviewer for it in items})
        findings.append(
            Finding(
                severity=severity,
                consensus=len(models_reporting),
                category=cat,
                issue=issue,
                detail=detail,
                category_detail=cat_detail,
                models_reporting=models_reporting,
            )
        )
    return findings, result


def _share_issue(a: str, b: str) -> bool:
    """Conservative match used as a last-ditch heuristic when source_indices missing."""
    toks_a = set(_tokens(a))
    toks_b = set(_tokens(b))
    if not toks_a or not toks_b:
        return False
    return _jaccard(toks_a, toks_b) >= 0.4
