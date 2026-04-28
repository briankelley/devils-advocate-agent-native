"""Integration tests for run_lite_review with providers fully mocked."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from dvad_agent import review as _review
from dvad_agent.providers import ProviderResult
from dvad_agent.types import ReviewContext


pytestmark = pytest.mark.asyncio


def _ok_findings_json(severity="high", issue="missing failure mode"):
    return json.dumps(
        {
            "findings": [
                {
                    "severity": severity,
                    "category": "reliability",
                    "issue": issue,
                    "detail": "expand on what happens when redis is unreachable",
                }
            ]
        }
    )


class _FakeClient:
    pass


async def _run(
    artifact="Plan: rate limit /api/*",
    artifact_type="plan",
    context=None,
    **kwargs,
):
    return await _review.run_lite_review(
        _FakeClient(),
        artifact=artifact,
        artifact_type=artifact_type,
        context=context or ReviewContext(),
        **kwargs,
    )


async def test_setup_required_when_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    resp = await _run()
    assert resp.status == "setup_required"


async def test_happy_path_ok(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake_call_with_retry(client, model, system, user, **kw):
        return ProviderResult(text=_ok_findings_json(), input_tokens=500, output_tokens=200)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake_call_with_retry), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake_call_with_retry):
        resp = await _run()
    assert resp.status == "ok"
    assert resp.body["outcome"] in ("clean", "caution", "critical_found")
    assert resp.body["report_markdown"].startswith("# dvad review")


async def test_skipped_secrets_on_abort(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    fake_aws_token = "AKIA" + "Z" * 16
    bad_artifact = f"here is a leaked key: {fake_aws_token}"
    resp = await _run(artifact=bad_artifact)
    assert resp.status == "skipped_secrets"
    assert any(
        m["pattern_type"] == "aws_access_key" for m in resp.body["matches"]
    )


async def test_redact_mode_proceeds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("DVAD_SECRETS_MODE", "redact")

    fake_aws_token = "AKIA" + "Z" * 16

    async def fake_call_with_retry(client, model, system, user, **kw):
        # Confirm the redacted payload no longer contains the raw secret.
        assert fake_aws_token not in user
        return ProviderResult(text=_ok_findings_json(), input_tokens=100, output_tokens=50)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake_call_with_retry), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake_call_with_retry):
        resp = await _run(artifact=f"some plan content {fake_aws_token} xxx")
    assert resp.status == "ok"
    assert len(resp.body["redacted_locations"]) >= 1


async def test_failed_review_when_only_one_reviewer_succeeds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    call_count = {"n": 0}

    async def fake(client, model, system, user, **kw):
        call_count["n"] += 1
        if call_count["n"] <= 3:  # fail most reviewers
            raise RuntimeError("simulated provider failure")
        return ProviderResult(text=_ok_findings_json(), input_tokens=100, output_tokens=50)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "failed_review"
    assert resp.body["reviewer_errors"]


async def test_invalid_request_reference_files_without_repo_root(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    resp = await _run(
        context=ReviewContext(reference_files=["some/file.py"], repo_root=None)
    )
    assert resp.status == "invalid_request"


async def test_skipped_budget_when_daily_cap_exceeded(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "0.0001")  # tiny cap

    resp = await _run()
    assert resp.status == "skipped_budget"


async def test_critical_finding_drives_outcome(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake(client, model, system, user, **kw):
        return ProviderResult(
            text=_ok_findings_json(severity="critical", issue="hard crash path"),
            input_tokens=100, output_tokens=50,
        )

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    assert resp.body["outcome"] == "critical_found"


async def test_degraded_flag_on_lost_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake(client, model, system, user, **kw):
        # Fail both openai reviewers, let anthropic succeed
        if model.provider == "openai":
            raise RuntimeError("openai is down")
        return ProviderResult(text=_ok_findings_json(), input_tokens=100, output_tokens=50)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    assert resp.body["degraded"] is True


async def test_degraded_false_when_all_providers_represented(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    call_counts: dict[str, int] = {}

    async def fake(client, model, system, user, **kw):
        key = model.provider
        call_counts[key] = call_counts.get(key, 0) + 1
        # Fail only the SECOND reviewer per provider (a redundant one)
        if call_counts[key] >= 2:
            raise RuntimeError("second reviewer in this provider failed")
        return ProviderResult(text=_ok_findings_json(), input_tokens=100, output_tokens=50)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    # All planned providers still represented → degraded=False
    assert resp.body["degraded"] is False


async def test_token_usage_present_in_ok_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake(client, model, system, user, **kw):
        return ProviderResult(text=_ok_findings_json(), input_tokens=500, output_tokens=200)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    assert "token_usage" in resp.body
    assert "tokens_total" in resp.body
    assert len(resp.body["token_usage"]) >= 2
    total = sum(
        u["input_tokens"] + u["output_tokens"] for u in resp.body["token_usage"]
    )
    assert resp.body["tokens_total"] == total


async def test_token_usage_cost_derived_from_entries(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake(client, model, system, user, **kw):
        return ProviderResult(text=_ok_findings_json(), input_tokens=500, output_tokens=200)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    entry_sum = sum(u["cost_usd"] or 0.0 for u in resp.body["token_usage"])
    assert abs(resp.body["cost_usd"] - entry_sum) < 1e-6


async def test_failed_review_includes_token_usage(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    call_count = {"n": 0}

    async def fake(client, model, system, user, **kw):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            raise RuntimeError("simulated provider failure")
        return ProviderResult(text=_ok_findings_json(), input_tokens=100, output_tokens=50)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "failed_review"
    assert "token_usage" in resp.body
    assert "tokens_total" in resp.body
    assert "cost_usd" in resp.body
    assert "pricing_unavailable" in resp.body


async def test_failed_reviewer_has_zero_tokens(monkeypatch):
    """Timeout/connection-error reviewers get zero tokens and cost_usd=0.0."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    async def fake(client, model, system, user, **kw):
        if model.provider == "openai":
            raise RuntimeError("provider down")
        return ProviderResult(text=_ok_findings_json(), input_tokens=500, output_tokens=200)

    with patch("dvad_agent.review.call_with_retry", side_effect=fake), \
         patch("dvad_agent.dedup.call_with_retry", side_effect=fake):
        resp = await _run()
    assert resp.status == "ok"
    for entry in resp.body["token_usage"]:
        if entry["provider"] == "openai" and entry["role"] == "reviewer":
            assert entry["input_tokens"] == 0
            assert entry["output_tokens"] == 0
            assert entry["cost_usd"] == 0.0
