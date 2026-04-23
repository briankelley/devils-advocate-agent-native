import pytest

from dvad_agent.providers import (
    parse_and_validate_findings,
    sanitize_json_output,
)


def test_sanitize_strips_fences():
    raw = '```json\n{"findings": []}\n```'
    assert sanitize_json_output(raw).strip() == '{"findings": []}'


def test_sanitize_plain_object():
    raw = '{"findings": [{"severity": "high", "category": "security", "issue": "x"}]}'
    assert sanitize_json_output(raw) == raw


def test_parse_valid_findings():
    raw = (
        '{"findings": ['
        '{"severity": "critical", "category": "security", '
        '"issue": "SQLi risk", "detail": "user input flows directly into query"}'
        "]}"
    )
    parsed, err = parse_and_validate_findings(raw, "m", "p")
    assert err is None
    assert parsed is not None
    assert parsed[0]["severity"] == "critical"


def test_parse_failure_preserves_raw():
    raw = "this is not json"
    parsed, err = parse_and_validate_findings(raw, "m", "p")
    assert parsed is None
    assert err is not None
    assert err.error_type.value == "parse_failure"
    assert err.raw_response == raw


def test_schema_invalid_missing_issue():
    raw = '{"findings": [{"severity": "high", "category": "security"}]}'
    parsed, err = parse_and_validate_findings(raw, "m", "p")
    assert parsed is None
    assert err is not None
    assert err.error_type.value == "schema_invalid"


def test_schema_invalid_root_not_object():
    raw = '[{"severity": "high", "category": "security", "issue": "x"}]'
    parsed, err = parse_and_validate_findings(raw, "m", "p")
    assert parsed is None
    assert err.error_type.value == "schema_invalid"


def test_parse_empty_findings():
    raw = '{"findings": []}'
    parsed, err = parse_and_validate_findings(raw, "m", "p")
    assert err is None
    assert parsed == []
