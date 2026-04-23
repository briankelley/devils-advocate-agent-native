from dvad_agent.dedup import DedupInput, deterministic_dedup
from dvad_agent.types import Category, Severity


def _item(reviewer, severity, category, issue, detail=""):
    return DedupInput(
        reviewer=reviewer,
        severity=severity,
        category=category,
        issue=issue,
        detail=detail,
    )


def test_three_identical_findings_merge_to_one():
    items = [
        _item("m1", "high", "correctness", "off-by-one in pagination offset"),
        _item("m2", "high", "correctness", "off-by-one in pagination offset"),
        _item("m3", "high", "correctness", "off-by-one in pagination offset"),
    ]
    out = deterministic_dedup(items)
    assert len(out) == 1
    assert out[0].consensus == 3
    assert out[0].severity == Severity.HIGH
    assert out[0].category == Category.CORRECTNESS


def test_distinct_findings_stay_separate():
    items = [
        _item("m1", "high", "security", "SQL injection in /login endpoint"),
        _item("m2", "high", "security", "SQL injection in /payment endpoint"),
    ]
    out = deterministic_dedup(items)
    # Short strings like these should NOT merge at the 0.7 threshold.
    assert len(out) == 2


def test_category_aware_prevents_false_merges():
    # Same-keyword overlap, different category, must not merge.
    items = [
        _item("m1", "medium", "security", "missing auth on login route"),
        _item("m2", "medium", "testing", "missing test for login route"),
    ]
    out = deterministic_dedup(items)
    assert len(out) == 2


def test_severity_merge_takes_max():
    items = [
        _item("m1", "low", "correctness", "same issue to merge"),
        _item("m2", "critical", "correctness", "same issue to merge"),
    ]
    out = deterministic_dedup(items)
    assert len(out) == 1
    assert out[0].severity == Severity.CRITICAL


def test_dedup_is_deterministic():
    items = [
        _item("m1", "high", "correctness", "boundary condition misses empty input"),
        _item("m2", "high", "correctness", "boundary condition misses empty input"),
        _item("m3", "medium", "performance", "quadratic scan in hot path"),
    ]
    out1 = deterministic_dedup(items)
    out2 = deterministic_dedup(items)
    assert [(f.severity, f.category, f.issue) for f in out1] == [
        (f.severity, f.category, f.issue) for f in out2
    ]
