"""Markdown renderer for review results.

JSON and markdown share a single source-of-truth dataclass (ReviewResult);
this module is the only place that differs.
"""

from __future__ import annotations

from .types import (
    Finding,
    ReviewResult,
    SEVERITY_RANK,
    Severity,
    WarningLevel,
)


def _severity_sort_key(f: Finding) -> int:
    return -SEVERITY_RANK[f.severity]


def render_markdown(result: ReviewResult) -> str:
    lines: list[str] = []
    lines.append(f"# dvad review — {result.artifact_type}")
    lines.append("")
    lines.append(f"- **Outcome:** `{result.outcome.value}`")
    lines.append(f"- **Review ID:** `{result.review_id}`")
    if result.parent_review_id:
        lines.append(f"- **Parent review:** `{result.parent_review_id}`")
    lines.append(f"- **Duration:** {result.duration_seconds:.1f}s")
    lines.append(f"- **Cost:** ${result.cost_usd:.4f}")
    lines.append(f"- **Models used:** {', '.join(result.models_used)}")
    lines.append("")

    # Banners
    banners: list[str] = []
    if result.degraded:
        banners.append(
            "> ⚠ **Degraded coverage** — one or more reviewers failed and a "
            "planned provider is no longer represented in this review."
        )
    if result.diversity_warning:
        banners.append(
            "> ⚠ **Single-provider review** — all reviewers came from the same "
            "provider. Findings are more correlated than a multi-provider run."
        )
    if result.dedup_method == "deterministic":
        banners.append(
            "> ℹ **Deterministic dedup** — the model-based dedup was unavailable "
            "or timed out. Same-category findings may have been conservatively "
            "merged or split; review individual entries before acting."
        )
    if result.pricing_unavailable:
        banners.append(
            "> ℹ **Pricing unavailable** — one or more models have no pricing "
            "metadata. Cost figures may be incomplete."
        )
    if result.budget_status.warning_level == WarningLevel.HARD:
        banners.append(
            f"> ⚠ **Daily budget 85%+** — ${result.budget_status.spent_usd:.2f} of "
            f"${result.budget_status.cap_usd:.2f} spent today."
        )
    elif result.budget_status.warning_level == WarningLevel.SOFT:
        banners.append(
            f"> ℹ **Daily budget 70%+** — ${result.budget_status.spent_usd:.2f} of "
            f"${result.budget_status.cap_usd:.2f} spent today."
        )
    for b in banners:
        lines.append(b)
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(result.summary)
    lines.append("")

    # Grouped findings
    ordered = sorted(result.findings, key=_severity_sort_key)
    grouped: dict[Severity, list[Finding]] = {}
    for f in ordered:
        grouped.setdefault(f.severity, []).append(f)

    if ordered:
        lines.append("## Findings")
        lines.append("")
        for severity in (
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
            Severity.INFO,
        ):
            if severity not in grouped:
                continue
            lines.append(f"### {severity.value.title()}")
            lines.append("")
            for f in grouped[severity]:
                consensus_str = (
                    f"{f.consensus}/{len(f.models_reporting)}"
                    if f.models_reporting
                    else str(f.consensus)
                )
                cat_str = f.category.value
                if f.category_detail:
                    cat_str = f"{cat_str} ({f.category_detail})"
                lines.append(f"- **[{consensus_str} · {cat_str}]** {f.issue}")
                if f.detail:
                    lines.append(f"  - {f.detail}")
                if f.models_reporting:
                    lines.append(
                        f"  - reported by: {', '.join(f.models_reporting)}"
                    )
            lines.append("")

    # Reviewer errors
    if result.reviewer_errors:
        lines.append("## Reviewer errors")
        lines.append("")
        for err in result.reviewer_errors:
            lines.append(
                f"- **{err.model_name}** ({err.provider}): "
                f"`{err.error_type.value}` — {err.message}"
            )
        lines.append("")

    # Redaction locations
    if result.redacted_locations:
        lines.append("## Redacted locations")
        lines.append("")
        lines.append(f"Artifact SHA-256: `{result.original_artifact_sha256}`")
        lines.append("")
        for m in result.redacted_locations:
            start, end = m.approx_line_range
            span = f"lines {start}–{end}" if start != end else f"line {start}"
            lines.append(f"- `{m.pattern_type}` in `{m.channel}` ({span})")
        lines.append("")

    # Budget footer
    lines.append("---")
    lines.append(
        f"daily budget: ${result.budget_status.spent_usd:.2f} / "
        f"${result.budget_status.cap_usd:.2f} "
        f"({result.budget_status.warning_level.value})"
    )
    return "\n".join(lines)
