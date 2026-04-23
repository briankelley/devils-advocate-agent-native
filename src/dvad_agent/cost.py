"""Token estimation, cost math, context-window preflight.

Following plan §3 Phase 1: when pricing is unavailable for a model, return
``None`` — never invent a conservative default.
"""

from __future__ import annotations

from .types import ModelConfig

CHARS_PER_TOKEN = 4
CONTEXT_WINDOW_THRESHOLD = 0.8  # reserve 20% for output / safety


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_cost(
    model: ModelConfig,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Return USD cost, or None if pricing metadata is unavailable."""
    if model.cost_per_1k_input is None or model.cost_per_1k_output is None:
        return None
    return (
        input_tokens / 1000 * model.cost_per_1k_input
        + output_tokens / 1000 * model.cost_per_1k_output
    )


def check_context_window(
    model: ModelConfig,
    text: str,
) -> tuple[bool, int, int]:
    """Return ``(fits, estimated_tokens, limit)``.

    ``limit`` is 0 when the model has no declared context window — in which case
    ``fits`` is always True.
    """
    est = estimate_tokens(text)
    if model.context_window is None:
        return True, est, 0
    limit = int(model.context_window * CONTEXT_WINDOW_THRESHOLD)
    return est <= limit, est, limit
