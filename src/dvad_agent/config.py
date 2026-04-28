"""Env-key detection, base-URL detection, default model table, diversity warning,
logging setup with API-key redaction.

Zero-config means: with API keys in env and no config file, the server picks
sensible defaults and runs. ``models.yaml`` is an override path, never a
prerequisite.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from .types import ModelConfig, SecretsMode


# ─── Env var names ────────────────────────────────────────────────────────────

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_OPENAI_KEY = "OPENAI_API_KEY"
ENV_GOOGLE_KEYS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
ENV_ANTHROPIC_BASE = "ANTHROPIC_BASE_URL"
ENV_OPENAI_BASE = "OPENAI_BASE_URL"

ENV_BUDGET_PER_REVIEW = "DVAD_BUDGET_PER_REVIEW"
ENV_BUDGET_DAILY = "DVAD_BUDGET_DAILY"
ENV_SECRETS_MODE = "DVAD_SECRETS_MODE"
ENV_LOG_LEVEL = "DVAD_LOG_LEVEL"
ENV_PERSIST_REVIEWS = "DVAD_PERSIST_REVIEWS"
ENV_DVAD_HOME = "DVAD_HOME"

DEFAULT_BUDGET_PER_REVIEW = 2.00
DEFAULT_BUDGET_DAILY = 50.00


# ─── Default model table ──────────────────────────────────────────────────────

# Two reviewer-role models per provider + one non-reasoning dedup model.
# See plan §3 Phase 1: "Default model table (revised — two reviewer-role
# models per provider)". Non-reasoning dedup models are mandatory for hitting
# latency budget. All reviewers run with thinking_enabled=False for speed.
#
# Updated 2026-04-23: gpt-4o/4.1 → gpt-5.2/5.4-mini, gemini-2.5-flash →
# gemini-3-flash/pro-preview, opus → sonnet-4-5. Prior defaults were stale —
# older models at higher cost with lower capability.
_DEFAULT_MODEL_TABLE: dict[str, list[dict[str, Any]]] = {
    "anthropic": [
        # Opus models only. Sonnet has been unreliable since early 2026 —
        # quality regressions make it unsuitable for adversarial review.
        # Two Opus generations for intra-provider diversity.
        {
            "model_id": "claude-opus-4-7",
            "role": "reviewer",
            "cost_per_1k_input": 0.005,
            "cost_per_1k_output": 0.025,
            "context_window": 200_000,
            "max_output_tokens": 3000,
        },
        {
            "model_id": "claude-opus-4-6",
            "role": "reviewer",
            "cost_per_1k_input": 0.005,
            "cost_per_1k_output": 0.025,
            "context_window": 200_000,
            "max_output_tokens": 3000,
        },
        {
            "model_id": "claude-haiku-4-5-20251001",
            "role": "dedup",
            "cost_per_1k_input": 0.001,
            "cost_per_1k_output": 0.005,
            "context_window": 200_000,
            "max_output_tokens": 2000,
            "thinking_enabled": False,
        },
    ],
    "openai": [
        {
            "model_id": "gpt-5.2",
            "role": "reviewer",
            "cost_per_1k_input": 0.00175,
            "cost_per_1k_output": 0.014,
            "context_window": 400_000,
            "max_output_tokens": 1500,
        },
        {
            "model_id": "gpt-5.4-mini",
            "role": "reviewer",
            "cost_per_1k_input": 0.00075,
            "cost_per_1k_output": 0.0045,
            "context_window": 400_000,
            "max_output_tokens": 1500,
        },
        {
            "model_id": "gpt-5.4-nano",
            "role": "dedup",
            "cost_per_1k_input": 0.0002,
            "cost_per_1k_output": 0.00125,
            "context_window": 400_000,
            "max_output_tokens": 2000,
            "thinking_enabled": False,
        },
    ],
    "google": [
        {
            "model_id": "gemini-3-flash-preview",
            "role": "reviewer",
            "cost_per_1k_input": 0.0005,
            "cost_per_1k_output": 0.003,
            "context_window": 1_000_000,
            "max_output_tokens": 1500,
        },
        # gemini-3-pro-preview refuses thinking-disabled mode (same as
        # gemini-2.5-pro — "Budget 0 is invalid. This model only works in
        # thinking mode"). Pro is a power-user override via models.yaml with
        # thinking_enabled=True. Default second Google reviewer is the prior
        # generation flash, which handles thinking-off reliably.
        {
            "model_id": "gemini-2.5-flash",
            "role": "reviewer",
            "cost_per_1k_input": 0.0003,
            "cost_per_1k_output": 0.0025,
            "context_window": 1_000_000,
            "max_output_tokens": 1500,
        },
    ],
}

# Gemini flash also serves as the dedup fallback for google-only setups.
_GOOGLE_DEDUP_MODEL: dict[str, Any] = {
    "model_id": "gemini-3-flash-preview",
    "role": "dedup",
    "cost_per_1k_input": 0.0005,
    "cost_per_1k_output": 0.003,
    "context_window": 1_000_000,
    "max_output_tokens": 2000,
}

_PROVIDER_DEFAULT_BASES = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com",
}


# ─── Detection ────────────────────────────────────────────────────────────────


def detect_providers() -> dict[str, dict[str, str]]:
    """Return ``{provider: {api_key, api_base}}`` for every provider whose key
    is present in the environment."""
    providers: dict[str, dict[str, str]] = {}

    if os.environ.get(ENV_ANTHROPIC_KEY):
        providers["anthropic"] = {
            "api_key": os.environ[ENV_ANTHROPIC_KEY],
            "api_base": os.environ.get(ENV_ANTHROPIC_BASE)
            or _PROVIDER_DEFAULT_BASES["anthropic"],
        }

    if os.environ.get(ENV_OPENAI_KEY):
        providers["openai"] = {
            "api_key": os.environ[ENV_OPENAI_KEY],
            "api_base": os.environ.get(ENV_OPENAI_BASE)
            or _PROVIDER_DEFAULT_BASES["openai"],
        }

    for env_name in ENV_GOOGLE_KEYS:
        if os.environ.get(env_name):
            providers["google"] = {
                "api_key": os.environ[env_name],
                "api_base": _PROVIDER_DEFAULT_BASES["google"],
            }
            break

    return providers


def _apply_overrides(entry: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Override-on-top, but never erase provider/model identity."""
    merged = dict(entry)
    for k, v in override.items():
        if k in ("provider", "model_id"):
            continue
        merged[k] = v
    return merged


def _load_models_yaml_overrides() -> dict[str, Any]:
    """Search order: project-local → $DVAD_HOME → XDG."""
    candidates: list[Path] = []
    local = Path("models.yaml")
    if local.is_file():
        candidates.append(local)
    dvad_home = os.environ.get(ENV_DVAD_HOME)
    if dvad_home:
        p = Path(dvad_home) / "models.yaml"
        if p.is_file():
            candidates.append(p)
    xdg = Path.home() / ".config" / "devils-advocate-agent" / "models.yaml"
    if xdg.is_file():
        candidates.append(xdg)

    if not candidates:
        return {}
    try:
        with candidates[0].open() as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("dvad_agent").warning(
            "Failed to parse %s (ignoring): %s", candidates[0], exc
        )
        return {}


def build_model_table(
    providers: dict[str, dict[str, str]] | None = None,
) -> tuple[list[ModelConfig], list[ModelConfig]]:
    """Assemble the live reviewer and dedup model lists.

    Returns ``(reviewers, dedup_candidates)``. Reviewers are ordered so that
    cross-provider picks come first.
    """
    if providers is None:
        providers = detect_providers()

    overrides = _load_models_yaml_overrides()
    override_map: dict[str, dict[str, Any]] = {}
    for block in (overrides.get("models") or {}).values() if isinstance(overrides, dict) else []:
        # overrides.models is allowed to be either list or map; keep it simple
        pass  # map form handled below
    if isinstance(overrides.get("models"), dict):
        for name, cfg in overrides["models"].items():
            if isinstance(cfg, dict):
                override_map[name] = cfg

    reviewers: list[ModelConfig] = []
    dedup: list[ModelConfig] = []

    for provider, defs in _DEFAULT_MODEL_TABLE.items():
        if provider not in providers:
            continue
        pinfo = providers[provider]
        for entry in defs:
            merged = _apply_overrides(entry, override_map.get(entry["model_id"], {}))
            mc = ModelConfig(
                provider=provider,
                model_id=merged["model_id"],
                api_key=pinfo["api_key"],
                api_base=pinfo["api_base"],
                cost_per_1k_input=merged.get("cost_per_1k_input"),
                cost_per_1k_output=merged.get("cost_per_1k_output"),
                context_window=merged.get("context_window"),
                max_output_tokens=merged.get("max_output_tokens", 1500),
                thinking_enabled=bool(merged.get("thinking_enabled", False)),
                use_responses_api=bool(merged.get("use_responses_api", False)),
                use_openai_compat=bool(merged.get("use_openai_compat", False)),
                role=merged.get("role", "reviewer"),
                name=merged.get("name") or merged["model_id"],
            )
            if mc.role == "reviewer":
                reviewers.append(mc)
            elif mc.role == "dedup":
                dedup.append(mc)

        # google-only setups fall back to flash for dedup
        if provider == "google" and not any(d.provider == "google" for d in dedup):
            extra = _apply_overrides(_GOOGLE_DEDUP_MODEL, {})
            dedup.append(
                ModelConfig(
                    provider="google",
                    model_id=extra["model_id"],
                    api_key=pinfo["api_key"],
                    api_base=pinfo["api_base"],
                    cost_per_1k_input=extra.get("cost_per_1k_input"),
                    cost_per_1k_output=extra.get("cost_per_1k_output"),
                    context_window=extra.get("context_window"),
                    max_output_tokens=extra.get("max_output_tokens", 2000),
                    role="dedup",
                    name=extra["model_id"],
                )
            )

    # Order reviewers: cross-provider diversity first — pick one from each
    # distinct provider before a second from the same provider.
    reviewers.sort(key=lambda m: (m.provider, m.model_id))
    seen_providers: set[str] = set()
    ordered: list[ModelConfig] = []
    secondary: list[ModelConfig] = []
    for m in reviewers:
        if m.provider in seen_providers:
            secondary.append(m)
        else:
            ordered.append(m)
            seen_providers.add(m.provider)
    reviewers = ordered + secondary

    return reviewers, dedup


def minimum_met(reviewers: list[ModelConfig]) -> bool:
    """True when ≥2 distinct reviewer models are available (spec: may be same provider)."""
    return len({m.model_id for m in reviewers}) >= 2


def compute_diversity_warning(reviewers: list[ModelConfig]) -> bool:
    """True when all active reviewers share a single provider."""
    providers = {m.provider for m in reviewers}
    return len(providers) <= 1 and len(reviewers) >= 1


# ─── Secrets mode / budget ────────────────────────────────────────────────────


def get_secrets_mode() -> SecretsMode:
    raw = os.environ.get(ENV_SECRETS_MODE, "abort").strip().lower()
    try:
        return SecretsMode(raw)
    except ValueError:
        logging.getLogger("dvad_agent").warning(
            "Invalid %s=%r; defaulting to abort", ENV_SECRETS_MODE, raw
        )
        return SecretsMode.ABORT


def get_budget_per_review() -> float:
    raw = os.environ.get(ENV_BUDGET_PER_REVIEW)
    if raw is None:
        return DEFAULT_BUDGET_PER_REVIEW
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_BUDGET_PER_REVIEW


def get_budget_daily() -> float:
    raw = os.environ.get(ENV_BUDGET_DAILY)
    if raw is None:
        return DEFAULT_BUDGET_DAILY
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_BUDGET_DAILY


def daily_cap_disabled() -> bool:
    return get_budget_daily() == 0


def get_persist_reviews() -> bool:
    return os.environ.get(ENV_PERSIST_REVIEWS, "").strip() in ("1", "true", "yes")


# ─── Logging with API-key redaction ───────────────────────────────────────────


_REDACT_HEADERS = ("authorization", "x-api-key", "x-goog-api-key")
_REDACT_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(AIza[A-Za-z0-9_-]{20,})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
]


class RedactionFilter(logging.Filter):
    """Scrub API keys and auth headers from log records before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        redacted = msg
        lower = redacted.lower()
        for header in _REDACT_HEADERS:
            # Redact header values if they appear as "header: value"
            idx = 0
            while True:
                i = lower.find(header + ":", idx)
                if i == -1:
                    i = lower.find(header + "=", idx)
                if i == -1:
                    break
                j = redacted.find("\n", i)
                if j == -1:
                    j = len(redacted)
                redacted = (
                    redacted[: i + len(header) + 1] + " <redacted>" + redacted[j:]
                )
                lower = redacted.lower()
                idx = i + len(header) + 1
        for pat in _REDACT_PATTERNS:
            redacted = pat.sub("<redacted>", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str | None = None) -> None:
    """Configure stdlib logging: stderr only, redaction filter attached.

    MCP stdio transport lives on stdout — any log output that reaches stdout
    would corrupt the transport. We reconfigure the root logger to be safe.
    """
    raw_level = (level or os.environ.get(ENV_LOG_LEVEL) or "info").upper()
    log_level = getattr(logging, raw_level, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    # Explicitly reconfigure root to prevent stdout handlers from sticking.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(log_level)

    # Attach redaction to httpx logger as well if it becomes active.
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.addFilter(RedactionFilter())

    agent_logger = logging.getLogger("dvad_agent")
    agent_logger.addFilter(RedactionFilter())


# ─── Snapshot used by CLI `config` subcommand + dvad_config MCP tool ──────────


def config_snapshot() -> dict[str, Any]:
    """Return a JSON-shaped snapshot of current config state."""
    import platform as _platform

    providers = detect_providers()
    reviewers, dedup = build_model_table(providers)
    reviewer_rows = [
        {
            "provider": m.provider,
            "model_id": m.model_id,
            "role": m.role,
            "pricing_available": (
                m.cost_per_1k_input is not None and m.cost_per_1k_output is not None
            ),
            "context_window": m.context_window,
            "max_output_tokens": m.max_output_tokens,
            "api_base": m.api_base,
        }
        for m in reviewers
    ]
    dedup_rows = [
        {
            "provider": m.provider,
            "model_id": m.model_id,
            "role": m.role,
            "pricing_available": (
                m.cost_per_1k_input is not None and m.cost_per_1k_output is not None
            ),
        }
        for m in dedup
    ]

    system = _platform.system()
    if system == "Linux":
        plat = "Linux"
        # Heuristic: WSL distros expose "microsoft" in uname release.
        if "microsoft" in _platform.release().lower():
            plat = "Windows-via-WSL"
    elif system == "Darwin":
        plat = "Darwin"
    elif system == "Windows":
        plat = "Windows"
    else:
        plat = system

    met = minimum_met(reviewers)
    result: dict[str, Any] = {
        "providers_detected": sorted(providers.keys()),
        "base_urls": {p: info["api_base"] for p, info in providers.items()},
        "reviewers": reviewer_rows,
        "dedup": dedup_rows,
        "minimum_met": met,
        "diversity_warning": compute_diversity_warning(reviewers),
        "budget": {
            "per_review_usd": get_budget_per_review(),
            "daily_usd": get_budget_daily(),
            "daily_cap_disabled": daily_cap_disabled(),
        },
        "secrets_handling": get_secrets_mode().value,
        "persist_reviews": get_persist_reviews(),
        "platform": plat,
    }
    if not met:
        result["setup_required"] = {
            "message": (
                "dvad requires at least 2 reviewer models. Add API keys "
                "to the dvad MCP server's env block in ~/.claude.json, "
                "then restart the MCP server."
            ),
            "setup_steps": [
                "Open ~/.claude.json and find the dvad entry under mcpServers.",
                "Add your API keys to the \"env\" block:",
                "  \"ANTHROPIC_API_KEY\": \"sk-ant-...\"",
                "  \"OPENAI_API_KEY\": \"sk-...\"",
                "  \"GOOGLE_API_KEY\": \"AIza...\"   (optional third provider)",
                "At least 2 reviewer models are needed (one key with 2+ models, or two keys).",
                "Restart the MCP server or agent session to pick up new keys.",
                "Run dvad_config again to verify.",
            ],
            "docs_url": "https://github.com/briankelley/devils-advocate-agent-native#setup",
        }
    return result
