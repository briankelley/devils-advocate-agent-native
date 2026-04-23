"""Core dataclasses, enums, and the ToolResponse discriminated union.

All MCP tool responses carry a ``status`` field for clean agent-side branching.
Category and severity are closed enums — deterministic normalization is part of
the public contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─── Enums ────────────────────────────────────────────────────────────────────


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Ordering used by severity-max merge rules.
SEVERITY_RANK = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


class Category(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    TESTING = "testing"
    MAINTAINABILITY = "maintainability"
    COMPATIBILITY = "compatibility"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class Outcome(str, Enum):
    """Content severity only. Does NOT include ``degraded`` — that's a separate flag."""

    CLEAN = "clean"
    CAUTION = "caution"
    CRITICAL_FOUND = "critical_found"


class WarningLevel(str, Enum):
    NONE = "none"
    SOFT = "soft"  # ≥70% of daily cap
    HARD = "hard"  # ≥85% of daily cap


class ReviewerErrorType(str, Enum):
    TIMEOUT = "timeout"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    PARSE_FAILURE = "parse_failure"
    SCHEMA_INVALID = "schema_invalid"
    CONNECTION_ERROR = "connection_error"


class SecretsMode(str, Enum):
    ABORT = "abort"
    REDACT = "redact"
    SKIP = "skip"


# ─── Normalization table (hardcoded, versioned with package) ──────────────────


# Deterministic normalization is part of the tool contract; user-editable tables
# break reproducibility across environments. See plan §3 Phase 1 Types.
CATEGORY_NORMALIZATION_TABLE: dict[str, Category] = {
    # correctness family
    "correctness": Category.CORRECTNESS,
    "bug": Category.CORRECTNESS,
    "logic": Category.CORRECTNESS,
    "logic_error": Category.CORRECTNESS,
    # security family
    "security": Category.SECURITY,
    "vulnerability": Category.SECURITY,
    "sec": Category.SECURITY,
    "auth": Category.SECURITY,
    "authorization": Category.SECURITY,
    # performance family
    "performance": Category.PERFORMANCE,
    "perf": Category.PERFORMANCE,
    "efficiency": Category.PERFORMANCE,
    # reliability family
    "reliability": Category.RELIABILITY,
    "robustness": Category.RELIABILITY,
    "error_handling": Category.RELIABILITY,
    "resilience": Category.RELIABILITY,
    # testing family
    "testing": Category.TESTING,
    "tests": Category.TESTING,
    "test": Category.TESTING,
    "coverage": Category.TESTING,
    # maintainability family
    "maintainability": Category.MAINTAINABILITY,
    "readability": Category.MAINTAINABILITY,
    "style": Category.MAINTAINABILITY,
    "complexity": Category.MAINTAINABILITY,
    # compatibility family
    "compatibility": Category.COMPATIBILITY,
    "compat": Category.COMPATIBILITY,
    "portability": Category.COMPATIBILITY,
    # documentation family
    "documentation": Category.DOCUMENTATION,
    "docs": Category.DOCUMENTATION,
    "doc": Category.DOCUMENTATION,
    # other
    "other": Category.OTHER,
    "misc": Category.OTHER,
}


SEVERITY_NORMALIZATION_TABLE: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "crit": Severity.CRITICAL,
    "blocker": Severity.CRITICAL,
    "high": Severity.HIGH,
    "hi": Severity.HIGH,
    "major": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "med": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "low": Severity.LOW,
    "lo": Severity.LOW,
    "minor": Severity.LOW,
    "info": Severity.INFO,
    "informational": Severity.INFO,
    "note": Severity.INFO,
    "nit": Severity.INFO,
}


def normalize_severity(raw: str | None) -> Severity:
    if not raw:
        return Severity.MEDIUM
    key = str(raw).strip().lower()
    return SEVERITY_NORMALIZATION_TABLE.get(key, Severity.MEDIUM)


def normalize_category(raw: str | None) -> tuple[Category, str | None]:
    """Return (category, category_detail). ``category_detail`` is the original
    string when the input did not map cleanly — preserves the observed outlier.
    """
    if not raw:
        return Category.OTHER, None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    hit = CATEGORY_NORMALIZATION_TABLE.get(key)
    if hit is not None:
        return hit, None
    # Try prefix
    head = key.split("_")[0]
    hit = CATEGORY_NORMALIZATION_TABLE.get(head)
    if hit is not None:
        return hit, None
    return Category.OTHER, str(raw)


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class ModelConfig:
    provider: str  # "anthropic" | "openai" | "google" | ...
    model_id: str
    api_key: str = ""
    api_base: str = ""
    cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None
    context_window: int | None = None
    use_responses_api: bool = False  # OpenAI /v1/responses dispatch
    use_openai_compat: bool = False  # transport hint independent of provider identity
    thinking_enabled: bool = False  # reviewers default to disabled
    max_output_tokens: int = 1500  # role-specific cap
    role: str = "reviewer"  # "reviewer" | "dedup"
    name: str = ""  # display name; defaults to model_id if empty
    timeout: int = 120

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.model_id


@dataclass
class ProviderKey:
    provider: str
    api_key: str
    api_base: str | None = None


@dataclass
class Finding:
    severity: Severity
    consensus: int
    category: Category
    issue: str
    detail: str = ""
    category_detail: str | None = None
    models_reporting: list[str] = field(default_factory=list)


@dataclass
class ReviewerError:
    model_name: str
    provider: str
    error_type: ReviewerErrorType
    message: str
    raw_response: str | None = None  # preserved for parse/schema failures


@dataclass
class SecretMatch:
    pattern_type: str
    approx_line_range: tuple[int, int]
    channel: str  # "artifact" | "instructions" | "reference_file:<path>"


@dataclass
class BudgetStatus:
    spent_usd: float
    cap_usd: float
    remaining_usd: float
    warning_level: WarningLevel
    day: str  # YYYY-MM-DD


@dataclass
class ReviewContext:
    """Matches the spec's ``context`` parameter. Constructed by the server from
    the MCP tool payload before handing off to ``review.run_lite_review``.
    """

    project_name: str | None = None
    repo_root: str | None = None
    reference_files: list[str] = field(default_factory=list)
    instructions: str | None = None


@dataclass
class ReviewResult:
    review_id: str
    artifact_type: str
    mode: str  # always "lite" in v1
    outcome: Outcome
    degraded: bool  # independent of outcome
    diversity_warning: bool
    models_used: list[str]
    duration_seconds: float
    cost_usd: float
    findings: list[Finding]
    summary: str
    reviewer_errors: list[ReviewerError]
    dedup_method: str  # "model" | "deterministic"
    dedup_skipped: bool
    redacted_locations: list[SecretMatch]
    original_artifact_sha256: str
    budget_status: BudgetStatus
    report_markdown: str
    parent_review_id: str | None = None
    pricing_unavailable: bool = False


# ─── Tool response discriminated union ────────────────────────────────────────


@dataclass
class ToolResponse:
    """Discriminated union via ``status``. Clients branch on status.

    ``degraded`` is never a status — it is always a flag on an ``ok`` response.
    """

    status: str  # "ok" | "setup_required" | "skipped_budget" | "skipped_secrets"
    #           | "oversize_input" | "failed_review" | "invalid_request"
    body: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.body}
