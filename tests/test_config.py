from dvad_agent import config as _config


def test_no_keys_detected(monkeypatch):
    providers = _config.detect_providers()
    assert providers == {}


def test_single_anthropic_key_minimum_met_via_dual_reviewer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    reviewers, dedup = _config.build_model_table()
    assert len(reviewers) == 2  # sonnet-4-6 + sonnet-4-5
    assert _config.minimum_met(reviewers) is True
    assert _config.compute_diversity_warning(reviewers) is True


def test_two_providers_diversity_warning_off(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    reviewers, _ = _config.build_model_table()
    assert _config.compute_diversity_warning(reviewers) is False


def test_reviewer_order_prioritizes_cross_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    reviewers, _ = _config.build_model_table()
    first_two = {m.provider for m in reviewers[:2]}
    assert first_two == {"anthropic", "openai"}


def test_google_only_gets_dedup_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
    reviewers, dedup = _config.build_model_table()
    assert len(reviewers) == 2  # flash-preview + pro-preview
    assert any(m.model_id == "gemini-3-flash-preview" and m.role == "dedup" for m in dedup)


def test_openai_base_url_propagated(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    reviewers, _ = _config.build_model_table()
    assert all(r.api_base == "https://openrouter.ai/api/v1" for r in reviewers)


def test_secrets_mode_env_override(monkeypatch):
    monkeypatch.setenv("DVAD_SECRETS_MODE", "redact")
    assert _config.get_secrets_mode().value == "redact"
    monkeypatch.setenv("DVAD_SECRETS_MODE", "nonsense")
    assert _config.get_secrets_mode().value == "abort"


def test_budget_env_overrides(monkeypatch):
    monkeypatch.setenv("DVAD_BUDGET_PER_REVIEW", "7.5")
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "100")
    assert _config.get_budget_per_review() == 7.5
    assert _config.get_budget_daily() == 100
    assert _config.daily_cap_disabled() is False
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "0")
    assert _config.daily_cap_disabled() is True


def test_config_snapshot_includes_public_contract_fields(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    snap = _config.config_snapshot()
    for key in (
        "providers_detected",
        "reviewers",
        "dedup",
        "minimum_met",
        "diversity_warning",
        "secrets_handling",
        "platform",
        "budget",
    ):
        assert key in snap
