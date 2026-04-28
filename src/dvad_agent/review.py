"""Lite-mode review orchestrator.

Implements the full pipeline from plan §3 Phase 4:
- Validate repo_root (only required when reference_files provided)
- Load reference files under repo_root with size caps
- Assemble reviewer payload; secrets pre-scan (payload 1)
- Context-window preflight (no silent truncation → oversize_input)
- Budget preflight
- Fan out reviewers via as_completed; emit progress; slow-review warning at 20s
- Fan-out sub-budget 25s, dedup sub-budget 10s, overall deadline 45s
- Partial-failure rule: ≥2 reviewer successes required
- Secrets pre-scan payload 2 (dedup input)
- Dedup once on final reviewer set
- Outcome derivation (content severity only)
- Degraded derivation (provider-coverage relative to pre-failure state)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Any, Callable

import httpx

from . import config as _config
from . import cost as _cost
from . import dedup as _dedup
from . import output as _output
from . import paths as _paths
from . import prompts as _prompts
from . import secrets as _secrets
from .budget import BudgetCorrupted, BudgetManager
from .providers import (
    call_with_retry,
    map_http_to_reviewer_error,
    parse_and_validate_findings,
)
from .types import (
    BudgetStatus,
    Category,
    Finding,
    ModelConfig,
    ModelTokenUsage,
    Outcome,
    ReviewContext,
    ReviewResult,
    ReviewerError,
    ReviewerErrorType,
    SEVERITY_RANK,
    SecretMatch,
    SecretsMode,
    Severity,
    ToolResponse,
    WarningLevel,
    normalize_category,
    normalize_severity,
)


log = logging.getLogger("dvad_agent.review")


DEFAULT_DEADLINE = 45.0
FANOUT_BUDGET = 25.0
DEDUP_BUDGET = 10.0
SLOW_WARNING = 20.0


ProgressCallback = Callable[[dict[str, Any]], None] | None


async def run_lite_review(
    client: httpx.AsyncClient,
    *,
    artifact: str,
    artifact_type: str,
    context: ReviewContext,
    budget_limit: float | None = None,
    parent_review_id: str | None = None,
    deadline_seconds: float = DEFAULT_DEADLINE,
    slow_warning_seconds: float = SLOW_WARNING,
    budget_manager: BudgetManager | None = None,
    progress: ProgressCallback = None,
) -> ToolResponse:
    t_start = time.monotonic()
    review_id = f"dvad_{uuid.uuid4().hex[:12]}"
    reviewers_full, dedup_models = _config.build_model_table()

    # First-run detection ─────────────────────────────────────────────────────
    if not reviewers_full or not _config.minimum_met(reviewers_full):
        return ToolResponse(
            status="setup_required",
            body={
                "review_id": review_id,
                "reason": (
                    "At least two reviewer-role models are required. Add API keys "
                    "to the dvad MCP server's env block in ~/.claude.json."
                ),
                "setup_steps": [
                    "Open ~/.claude.json and find the dvad entry under mcpServers.",
                    "Add your API keys to the \"env\" block:",
                    "  \"ANTHROPIC_API_KEY\": \"sk-ant-...\"",
                    "  \"OPENAI_API_KEY\": \"sk-...\"",
                    "At least 2 reviewer models are needed (one key with 2+ models, or two keys).",
                    "Restart the MCP server or agent session to pick up new keys.",
                    "Call dvad_config to verify detected providers.",
                ],
                "docs_url": "https://github.com/briankelley/devils-advocate-agent-native#setup",
            },
        )

    diversity_warning = _config.compute_diversity_warning(reviewers_full)
    planned_providers = {m.provider for m in reviewers_full}

    # Validate repo_root (only required if reference_files supplied) ─────────
    loaded_refs: list[_paths.LoadedReferenceFile] = []
    rejected_refs: list[_paths.RejectedReferenceFile] = []
    if context.reference_files:
        if not context.repo_root:
            return ToolResponse(
                status="invalid_request",
                body={
                    "review_id": review_id,
                    "reason": "reference_files requires a valid repo_root",
                },
            )
        try:
            repo_root = _paths.validate_repo_root(context.repo_root)
        except _paths.PathValidationError as exc:
            return ToolResponse(
                status="invalid_request",
                body={"review_id": review_id, "reason": str(exc)},
            )
        loaded_refs, rejected_refs = _paths.load_reference_files(
            repo_root, context.reference_files
        )

    # Assemble reviewer payload ──────────────────────────────────────────────
    reference_tuples = [(ref.relative_path, ref.content) for ref in loaded_refs]
    reviewer_prompt = _prompts.build_reviewer_user_prompt(
        artifact=artifact,
        artifact_type=artifact_type,
        instructions=context.instructions,
        reference_files=reference_tuples,
    )

    # Secrets pre-scan — payload 1 ───────────────────────────────────────────
    secrets_mode = _config.get_secrets_mode()
    scan_targets: list[tuple[str, str]] = [(artifact, "artifact")]
    if context.instructions:
        scan_targets.append((context.instructions, "instructions"))
    for ref in loaded_refs:
        scan_targets.append((ref.content, f"reference_file:{ref.relative_path}"))

    secret_matches: list[SecretMatch] = []
    for payload, channel in scan_targets:
        secret_matches.extend(_secrets.scan(payload, channel=channel))

    redacted_locations: list[SecretMatch] = []
    if secret_matches:
        if secrets_mode == SecretsMode.ABORT:
            return ToolResponse(
                status="skipped_secrets",
                body={
                    "review_id": review_id,
                    "reason": "Potential secrets detected in input. Re-run with "
                              "DVAD_SECRETS_MODE=redact to proceed with redaction, "
                              "or remove the secrets from the artifact.",
                    "matches": [
                        {
                            "pattern_type": m.pattern_type,
                            "approx_line_range": list(m.approx_line_range),
                            "channel": m.channel,
                        }
                        for m in secret_matches
                    ],
                },
            )
        if secrets_mode == SecretsMode.REDACT:
            # Re-assemble payload with redacted content.
            artifact_red = _secrets.redact(artifact, [])
            instructions_red = (
                _secrets.redact(context.instructions, []) if context.instructions else None
            )
            ref_red = [
                (ref.relative_path, _secrets.redact(ref.content, []))
                for ref in loaded_refs
            ]
            reviewer_prompt = _prompts.build_reviewer_user_prompt(
                artifact=artifact_red,
                artifact_type=artifact_type,
                instructions=instructions_red,
                reference_files=ref_red,
            )
            redacted_locations = secret_matches

    # Context-window preflight ───────────────────────────────────────────────
    per_model_fit: list[dict[str, Any]] = []
    any_oversize = False
    for m in reviewers_full:
        fits, est, limit = _cost.check_context_window(m, reviewer_prompt)
        per_model_fit.append(
            {
                "model": m.model_id,
                "provider": m.provider,
                "fits": fits,
                "estimated_tokens": est,
                "limit": limit,
            }
        )
        if not fits:
            any_oversize = True
    if any_oversize:
        return ToolResponse(
            status="oversize_input",
            body={
                "review_id": review_id,
                "reason": "Input exceeds one or more reviewer model context windows.",
                "per_model_fit": per_model_fit,
            },
        )

    # Budget preflight ───────────────────────────────────────────────────────
    bm = budget_manager or BudgetManager()
    projected = _estimate_review_cost(reviewers_full, dedup_models, reviewer_prompt)
    pricing_unavailable = projected is None

    per_review_cap = budget_limit if budget_limit is not None else _config.get_budget_per_review()
    try:
        would_exceed, status = await bm.would_exceed(projected or 0.0)
    except BudgetCorrupted as exc:
        return ToolResponse(
            status="skipped_budget",
            body={
                "review_id": review_id,
                "reason": f"Today's budget file is corrupted: {exc}",
                "budget_status": _budget_status_dict(
                    BudgetStatus(
                        spent_usd=0.0,
                        cap_usd=_config.get_budget_daily(),
                        remaining_usd=0.0,
                        warning_level=WarningLevel.HARD,
                        day="",
                    )
                ),
            },
        )

    if projected is not None and projected > per_review_cap:
        return ToolResponse(
            status="skipped_budget",
            body={
                "review_id": review_id,
                "reason": f"Estimated cost ${projected:.4f} exceeds per-review cap ${per_review_cap:.4f}.",
                "budget_status": _budget_status_dict(status),
            },
        )
    if would_exceed:
        return ToolResponse(
            status="skipped_budget",
            body={
                "review_id": review_id,
                "reason": "Daily budget would be exceeded by this review.",
                "budget_status": _budget_status_dict(status),
            },
        )

    # Fan out reviewers ──────────────────────────────────────────────────────
    if progress:
        progress({"event": "fanout_start", "reviewers": [m.model_id for m in reviewers_full]})

    reviewer_results: dict[str, tuple[list[dict] | None, ReviewerError | None, dict]] = {}
    tasks: dict[asyncio.Task, ModelConfig] = {}
    for m in reviewers_full:
        task = asyncio.create_task(
            _run_single_reviewer(client, m, reviewer_prompt, timeout=FANOUT_BUDGET)
        )
        tasks[task] = m

    fanout_deadline = t_start + min(FANOUT_BUDGET, deadline_seconds)
    slow_warning_fired = False
    pending = set(tasks.keys())
    while pending:
        timeout = max(0.1, fanout_deadline - time.monotonic())
        done, pending = await asyncio.wait(
            pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            break
        for task in done:
            model = tasks[task]
            try:
                findings, err, usage = task.result()
            except Exception as exc:  # noqa: BLE001
                err = map_http_to_reviewer_error(exc, model.name, model.provider)
                findings, usage = None, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            reviewer_results[model.model_id] = (findings, err, usage)
            if progress:
                progress(
                    {
                        "event": "reviewer_done",
                        "model": model.model_id,
                        "provider": model.provider,
                        "ok": findings is not None,
                    }
                )

        elapsed = time.monotonic() - t_start
        if (
            not slow_warning_fired
            and elapsed >= slow_warning_seconds
            and len(reviewer_results) < len(reviewers_full)
            and progress
        ):
            slow_warning_fired = True
            progress(
                {
                    "event": "slow_review",
                    "elapsed_seconds": elapsed,
                    "pending_reviewers": [
                        tasks[t].model_id for t in pending
                    ],
                }
            )

    # Cancel stragglers that didn't finish inside the fan-out budget
    for task in pending:
        model = tasks[task]
        task.cancel()
        reviewer_results[model.model_id] = (
            None,
            ReviewerError(
                model_name=model.name,
                provider=model.provider,
                error_type=ReviewerErrorType.DEADLINE_EXCEEDED,
                message=f"Exceeded fan-out budget of {FANOUT_BUDGET}s",
            ),
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
    if pending:
        # Allow cancellations to settle
        await asyncio.gather(*pending, return_exceptions=True)

    # Build token usage from all reviewer results (before partial-failure check)
    token_usage: list[ModelTokenUsage] = []
    for mid, (_f, _e, usage) in reviewer_results.items():
        model = reviewers_full_lookup(reviewers_full, mid)
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        if in_tok == 0 and out_tok == 0:
            entry_cost: float | None = 0.0
        else:
            entry_cost = _cost.estimate_cost(model, in_tok, out_tok)
        token_usage.append(ModelTokenUsage(
            model_id=model.model_id,
            provider=model.provider,
            role=model.role,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=entry_cost,
        ))

    # Partial-failure rule ───────────────────────────────────────────────────
    successes = [
        (reviewers_full_lookup(reviewers_full, mid), findings, usage)
        for mid, (findings, err, usage) in reviewer_results.items()
        if findings is not None and err is None
    ]
    errors = [err for (findings, err, _usage) in reviewer_results.values() if err is not None]

    if len(successes) < 2:
        cost_usd_total = sum(u.cost_usd or 0.0 for u in token_usage)
        await bm.record_spend(cost_usd_total)
        status = await bm.read_status()
        return ToolResponse(
            status="failed_review",
            body={
                "review_id": review_id,
                "reason": (
                    f"Only {len(successes)} reviewer(s) returned valid responses; "
                    "at least 2 are required."
                ),
                "reviewer_errors": [_err_dict(e) for e in errors],
                "token_usage": [_token_usage_dict(u) for u in token_usage],
                "tokens_total": sum(u.input_tokens + u.output_tokens for u in token_usage),
                "cost_usd": cost_usd_total,
                "pricing_unavailable": any(u.cost_usd is None for u in token_usage),
                "budget_status": _budget_status_dict(status),
            },
        )

    # Dedup input assembly ───────────────────────────────────────────────────
    dedup_items: list[_dedup.DedupInput] = []
    for model, findings, _usage in successes:
        for f in findings or []:
            dedup_items.append(
                _dedup.DedupInput(
                    reviewer=model.model_id,
                    severity=f["severity"],
                    category=f["category"],
                    issue=f["issue"],
                    detail=f.get("detail", ""),
                )
            )

    dedup_payload_text = _prompts.build_dedup_user_prompt(
        [
            {
                "reviewer": it.reviewer,
                "severity": it.severity,
                "category": it.category,
                "issue": it.issue,
                "detail": it.detail,
            }
            for it in dedup_items
        ]
    )
    # Secrets pre-scan — payload 2 ───────────────────────────────────────────
    if secrets_mode != SecretsMode.SKIP:
        dedup_matches = _secrets.scan(dedup_payload_text, channel="dedup_payload")
        if dedup_matches and secrets_mode == SecretsMode.ABORT:
            await bm.record_spend(cost_usd)
            status = await bm.read_status()
            return ToolResponse(
                status="skipped_secrets",
                body={
                    "review_id": review_id,
                    "reason": (
                        "Reviewer output echoed a potential secret. Dedup call "
                        "skipped. Re-run with DVAD_SECRETS_MODE=redact to allow "
                        "redaction."
                    ),
                    "matches": [
                        {
                            "pattern_type": m.pattern_type,
                            "approx_line_range": list(m.approx_line_range),
                            "channel": m.channel,
                        }
                        for m in dedup_matches
                    ],
                    "budget_status": _budget_status_dict(status),
                },
            )

    # Dedup ─────────────────────────────────────────────────────────────────
    if progress:
        progress({"event": "dedup_start", "items": len(dedup_items)})

    # Enforce the overall deadline — dedup may only consume the remaining
    # budget. If fan-out already burned through the wall clock, fall straight
    # to deterministic dedup instead of blowing past the 45s deadline.
    time_remaining = max(0.0, deadline_seconds - (time.monotonic() - t_start))
    dedup_window = min(DEDUP_BUDGET, time_remaining)
    final_findings, dedup_method, dedup_skipped, dedup_usage = await _run_dedup(
        client, dedup_items, dedup_models, successes, dedup_window=dedup_window,
    )

    # Append dedup token usage if it consumed tokens
    if dedup_usage.get("input_tokens", 0) > 0 and dedup_models:
        dedup_model = dedup_models[0]
        d_in = dedup_usage.get("input_tokens", 0)
        d_out = dedup_usage.get("output_tokens", 0)
        d_cost = _cost.estimate_cost(dedup_model, d_in, d_out)
        token_usage.append(ModelTokenUsage(
            model_id=dedup_model.model_id,
            provider=dedup_model.provider,
            role=dedup_model.role,
            input_tokens=d_in,
            output_tokens=d_out,
            cost_usd=d_cost,
        ))

    # Derive aggregates from token_usage (single source of truth)
    cost_usd = sum(u.cost_usd or 0.0 for u in token_usage)
    pricing_unavailable = any(u.cost_usd is None for u in token_usage)

    if progress:
        progress({"event": "dedup_done", "method": dedup_method, "findings": len(final_findings)})

    # Record spend ───────────────────────────────────────────────────────────
    try:
        budget_status = await bm.record_spend(cost_usd)
    except BudgetCorrupted as exc:  # noqa: BLE001
        log.warning("Budget corrupted on write: %s", exc)
        budget_status = await bm.read_status()

    # Outcome derivation (content severity only) ─────────────────────────────
    outcome = _derive_outcome(final_findings)

    # Degraded derivation (coverage relative to pre-failure state) ───────────
    surviving_providers = {m.provider for m, _f, _u in successes}
    degraded = False
    if errors and len(planned_providers) > 1:
        lost_providers = planned_providers - surviving_providers
        if lost_providers:
            degraded = True

    # Hash of original artifact (never the redacted version) ─────────────────
    sha = hashlib.sha256(artifact.encode("utf-8")).hexdigest()

    models_used = [m.model_id for m, _f, _u in successes]
    duration = time.monotonic() - t_start
    summary = _build_summary(final_findings, outcome, degraded, diversity_warning)

    result = ReviewResult(
        review_id=review_id,
        artifact_type=artifact_type,
        mode="lite",
        outcome=outcome,
        degraded=degraded,
        diversity_warning=diversity_warning,
        models_used=models_used,
        duration_seconds=duration,
        cost_usd=cost_usd,
        findings=final_findings,
        summary=summary,
        reviewer_errors=errors,
        dedup_method=dedup_method,
        dedup_skipped=dedup_skipped,
        redacted_locations=redacted_locations,
        original_artifact_sha256=sha,
        budget_status=budget_status,
        report_markdown="",  # filled in below
        parent_review_id=parent_review_id,
        pricing_unavailable=pricing_unavailable,
        token_usage=token_usage,
    )
    result.report_markdown = _output.render_markdown(result)

    return ToolResponse(
        status="ok",
        body=_result_to_dict(result, rejected_refs, per_model_fit),
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────


def reviewers_full_lookup(reviewers: list[ModelConfig], model_id: str) -> ModelConfig:
    for m in reviewers:
        if m.model_id == model_id:
            return m
    raise KeyError(model_id)


async def _run_single_reviewer(
    client: httpx.AsyncClient,
    model: ModelConfig,
    user_prompt: str,
    timeout: float,
) -> tuple[list[dict] | None, ReviewerError | None, dict]:
    try:
        async with asyncio.timeout(timeout):
            result = await call_with_retry(
                client, model, _prompts.REVIEWER_SYSTEM, user_prompt,
                max_output_tokens=model.max_output_tokens,
            )
    except asyncio.TimeoutError:
        return (
            None,
            ReviewerError(
                model_name=model.name,
                provider=model.provider,
                error_type=ReviewerErrorType.DEADLINE_EXCEEDED,
                message=f"Exceeded reviewer timeout {timeout}s",
            ),
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
    except Exception as exc:  # noqa: BLE001
        err = map_http_to_reviewer_error(exc, model.name, model.provider)
        return None, err, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    cost = _cost.estimate_cost(model, result.input_tokens, result.output_tokens) or 0.0
    usage = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": cost,
    }
    findings, err = parse_and_validate_findings(result.text, model.name, model.provider)
    if err is not None:
        return None, err, usage
    return findings, None, usage


def _estimate_review_cost(
    reviewers: list[ModelConfig],
    dedup_models: list[ModelConfig],
    prompt_text: str,
) -> float | None:
    total = 0.0
    any_unknown = False
    in_tokens = _cost.estimate_tokens(prompt_text)
    for m in reviewers:
        c = _cost.estimate_cost(m, in_tokens, m.max_output_tokens)
        if c is None:
            any_unknown = True
            continue
        total += c
    if dedup_models:
        m = dedup_models[0]
        # heuristic: 6 findings per reviewer × ~100 tokens each
        in_est = 6 * 100 * len(reviewers)
        out_est = 500
        c = _cost.estimate_cost(m, in_est, out_est)
        if c is None:
            any_unknown = True
        else:
            total += c
    if any_unknown and total == 0.0:
        return None
    return total


async def _run_dedup(
    client: httpx.AsyncClient,
    items: list[_dedup.DedupInput],
    dedup_models: list[ModelConfig],
    successes: list[tuple[ModelConfig, list[dict] | None, dict]],
    dedup_window: float = DEDUP_BUDGET,
) -> tuple[list[Finding], str, bool, dict]:
    """Run dedup with parallel fan-out, bounded by ``dedup_window``.

    All dedup candidates run simultaneously. The first valid result wins;
    remaining tasks are cancelled. This replaces the sequential fallback
    that let each candidate burn the full timeout independently (a bug
    that allowed 3 × 10s = 30s of dedup time on a 10s budget).

    Returns (findings, method, skipped, usage_dict_with_cost).
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if not items:
        return [], "deterministic", False, usage

    if dedup_window <= 0.5:
        return _dedup.deterministic_dedup(items), "deterministic", True, usage

    # Build candidate pool: designated dedup models + successful non-thinking
    # reviewer models as fallbacks.
    candidates: list[ModelConfig] = list(dedup_models)
    for m, _f, _u in successes:
        if m not in candidates and not m.thinking_enabled:
            candidates.append(m)

    if not candidates:
        findings = _dedup.deterministic_dedup(items)
        return findings, "deterministic", True, usage

    # Fan out all candidates in parallel. First valid result wins.
    import asyncio as _aio

    tasks: dict[_aio.Task, ModelConfig] = {}
    for cand in candidates:
        task = _aio.create_task(
            _dedup.model_dedup(client, items, cand, timeout_seconds=dedup_window),
            name=f"dedup-{cand.name}",
        )
        tasks[task] = cand

    pending = set(tasks.keys())
    try:
        async with _aio.timeout(dedup_window):
            while pending:
                done, pending = await _aio.wait(pending, return_when=_aio.FIRST_COMPLETED)
                for done_task in done:
                    try:
                        findings, pr = done_task.result()
                    except Exception:  # noqa: BLE001
                        continue
                    if findings is not None and pr is not None:
                        cand = tasks[done_task]
                        cost = _cost.estimate_cost(cand, pr.input_tokens, pr.output_tokens) or 0.0
                        usage = {
                            "input_tokens": pr.input_tokens,
                            "output_tokens": pr.output_tokens,
                            "cost_usd": cost,
                        }
                        return findings, "model", False, usage
    except TimeoutError:
        log.warning("All dedup candidates exceeded %.1fs window", dedup_window)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            if not task.done():
                try:
                    await task
                except (_aio.CancelledError, Exception):  # noqa: BLE001
                    pass

    # Deterministic fallback
    findings = _dedup.deterministic_dedup(items)
    return findings, "deterministic", True, usage


def _derive_outcome(findings: list[Finding]) -> Outcome:
    for f in findings:
        if f.severity == Severity.CRITICAL:
            return Outcome.CRITICAL_FOUND
    for f in findings:
        if f.severity == Severity.HIGH:
            return Outcome.CAUTION
    return Outcome.CLEAN


def _build_summary(
    findings: list[Finding],
    outcome: Outcome,
    degraded: bool,
    diversity_warning: bool,
) -> str:
    if not findings:
        tail = " (no findings)"
    else:
        by_sev: dict[Severity, int] = {}
        for f in findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        parts = [
            f"{n} {sev.value}"
            for sev, n in sorted(by_sev.items(), key=lambda kv: -SEVERITY_RANK[kv[0]])
        ]
        tail = " — " + ", ".join(parts)
    notes: list[str] = []
    if degraded:
        notes.append("degraded coverage")
    if diversity_warning:
        notes.append("single-provider")
    prefix = f"Outcome: {outcome.value}" + tail
    if notes:
        prefix += f" ({', '.join(notes)})"
    return prefix


def _err_dict(err: ReviewerError) -> dict:
    return {
        "model_name": err.model_name,
        "provider": err.provider,
        "error_type": err.error_type.value,
        "message": err.message,
    }


def _token_usage_dict(u: ModelTokenUsage) -> dict:
    return {
        "model_id": u.model_id,
        "provider": u.provider,
        "role": u.role,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cost_usd": u.cost_usd,
    }


def _budget_status_dict(status: BudgetStatus) -> dict:
    return {
        "spent_usd": status.spent_usd,
        "cap_usd": status.cap_usd,
        "remaining_usd": status.remaining_usd,
        "warning_level": status.warning_level.value,
        "day": status.day,
    }


def _finding_dict(f: Finding) -> dict:
    return {
        "severity": f.severity.value,
        "consensus": f.consensus,
        "category": f.category.value,
        "category_detail": f.category_detail,
        "issue": f.issue,
        "detail": f.detail,
        "models_reporting": f.models_reporting,
    }


def _result_to_dict(
    result: ReviewResult,
    rejected_refs: list[_paths.RejectedReferenceFile],
    per_model_fit: list[dict[str, Any]],
) -> dict:
    return {
        "review_id": result.review_id,
        "parent_review_id": result.parent_review_id,
        "artifact_type": result.artifact_type,
        "mode": result.mode,
        "outcome": result.outcome.value,
        "degraded": result.degraded,
        "diversity_warning": result.diversity_warning,
        "models_used": result.models_used,
        "duration_seconds": result.duration_seconds,
        "cost_usd": result.cost_usd,
        "findings": [_finding_dict(f) for f in result.findings],
        "summary": result.summary,
        "reviewer_errors": [_err_dict(e) for e in result.reviewer_errors],
        "dedup_method": result.dedup_method,
        "dedup_skipped": result.dedup_skipped,
        "redacted_locations": [
            {
                "pattern_type": m.pattern_type,
                "approx_line_range": list(m.approx_line_range),
                "channel": m.channel,
            }
            for m in result.redacted_locations
        ],
        "original_artifact_sha256": result.original_artifact_sha256,
        "budget_status": _budget_status_dict(result.budget_status),
        "pricing_unavailable": result.pricing_unavailable,
        "token_usage": [_token_usage_dict(u) for u in result.token_usage],
        "tokens_total": result.tokens_total,
        "report_markdown": result.report_markdown,
        "rejected_reference_files": [
            {"path": r.path, "reason": r.reason} for r in rejected_refs
        ],
        "per_model_fit": per_model_fit,
    }
