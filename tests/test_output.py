from dvad_agent.output import render_markdown
from dvad_agent.types import (
    BudgetStatus,
    Category,
    Finding,
    ModelTokenUsage,
    Outcome,
    ReviewResult,
    Severity,
    WarningLevel,
)


def _result(**overrides):
    base = dict(
        review_id="dvad_abc",
        artifact_type="plan",
        mode="lite",
        outcome=Outcome.CLEAN,
        degraded=False,
        diversity_warning=False,
        models_used=["claude-sonnet-4-6", "gpt-5"],
        duration_seconds=12.3,
        cost_usd=0.0456,
        findings=[],
        summary="Outcome: clean (no findings)",
        reviewer_errors=[],
        dedup_method="model",
        dedup_skipped=False,
        redacted_locations=[],
        original_artifact_sha256="deadbeef",
        budget_status=BudgetStatus(
            spent_usd=1.0, cap_usd=50.0, remaining_usd=49.0,
            warning_level=WarningLevel.NONE, day="2026-04-22",
        ),
        report_markdown="",
    )
    base.update(overrides)
    return ReviewResult(**base)


def test_clean_report_shape():
    md = render_markdown(_result())
    assert "# dvad review — plan" in md
    assert "Outcome:" in md
    assert "daily budget" in md


def test_degraded_banner_present_when_flag_true():
    md = render_markdown(_result(degraded=True))
    assert "Degraded coverage" in md


def test_diversity_banner_present_when_flag_true():
    md = render_markdown(_result(diversity_warning=True))
    assert "Single-provider review" in md


def test_deterministic_dedup_caveat():
    md = render_markdown(_result(dedup_method="deterministic"))
    assert "Deterministic dedup" in md


def test_pricing_unavailable_banner():
    md = render_markdown(_result(pricing_unavailable=True))
    assert "Pricing unavailable" in md


def test_hard_budget_banner():
    md = render_markdown(
        _result(
            budget_status=BudgetStatus(
                spent_usd=45.0, cap_usd=50.0, remaining_usd=5.0,
                warning_level=WarningLevel.HARD, day="2026-04-22",
            )
        )
    )
    assert "Daily budget 85%+" in md


def test_findings_grouped_by_severity():
    findings = [
        Finding(
            severity=Severity.CRITICAL, consensus=3, category=Category.SECURITY,
            issue="SQLi risk", detail="", models_reporting=["m1", "m2", "m3"],
        ),
        Finding(
            severity=Severity.MEDIUM, consensus=1, category=Category.TESTING,
            issue="No integration test", detail="", models_reporting=["m2"],
        ),
    ]
    md = render_markdown(_result(findings=findings, outcome=Outcome.CRITICAL_FOUND))
    crit_idx = md.index("### Critical")
    med_idx = md.index("### Medium")
    assert crit_idx < med_idx  # severity ordering correct


def test_tokens_total_in_header():
    usage = [
        ModelTokenUsage(
            model_id="claude-sonnet-4-6", provider="anthropic", role="reviewer",
            input_tokens=5000, output_tokens=1200, cost_usd=0.02,
        ),
        ModelTokenUsage(
            model_id="gpt-5", provider="openai", role="reviewer",
            input_tokens=5000, output_tokens=1100, cost_usd=0.03,
        ),
    ]
    md = render_markdown(_result(token_usage=usage))
    assert "**Tokens:** 12,300 total" in md


def test_token_breakdown_section():
    usage = [
        ModelTokenUsage(
            model_id="claude-sonnet-4-6", provider="anthropic", role="reviewer",
            input_tokens=5000, output_tokens=1200, cost_usd=0.0234,
        ),
        ModelTokenUsage(
            model_id="gpt-5", provider="openai", role="reviewer",
            input_tokens=4800, output_tokens=1100, cost_usd=None,
        ),
    ]
    md = render_markdown(_result(token_usage=usage))
    assert "## Token breakdown" in md
    assert "**claude-sonnet-4-6** (reviewer): 5,000 in / 1,200 out" in md
    assert "$0.0234" in md
    assert "n/a" in md


def test_token_breakdown_absent_when_empty():
    md = render_markdown(_result(token_usage=[]))
    assert "Token breakdown" not in md
