from dvad_agent.cost import check_context_window, estimate_cost, estimate_tokens
from dvad_agent.types import ModelConfig


def test_estimate_tokens_floor_at_one():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_estimate_cost_returns_none_for_unpriced():
    m = ModelConfig(provider="x", model_id="custom", cost_per_1k_input=None, cost_per_1k_output=None)
    assert estimate_cost(m, 1000, 500) is None


def test_estimate_cost_math():
    m = ModelConfig(provider="x", model_id="y", cost_per_1k_input=0.01, cost_per_1k_output=0.02)
    assert estimate_cost(m, 2000, 1000) == 0.02 + 0.02


def test_check_context_window_no_declared_window():
    m = ModelConfig(provider="x", model_id="y", context_window=None)
    fits, est, limit = check_context_window(m, "hello")
    assert fits is True
    assert limit == 0


def test_check_context_window_enforces_threshold():
    m = ModelConfig(provider="x", model_id="y", context_window=1000)
    big = "a" * 5000  # ~1250 tokens — above 80% of 1000
    fits, est, limit = check_context_window(m, big)
    assert fits is False
    assert limit == 800
