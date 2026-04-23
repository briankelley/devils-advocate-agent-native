"""Secrets pre-scan.

Invoked twice per review: once on the assembled reviewer payload before fan-out,
once on the dedup payload before the dedup call. Modes: abort (default), redact,
skip. ``skip`` is only selectable via env var — never via per-call tool parameter,
so an LLM-driven caller cannot downgrade the security control.
"""

from __future__ import annotations

import math
import re

from .types import SecretMatch


# ─── Patterns ─────────────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key_suspect", re.compile(r"\baws_secret_access_key\s*[=:]\s*\S{20,}", re.IGNORECASE)),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("stripe_live_key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{30,}\b")),
    ("github_pat_fine", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-api03-[A-Za-z0-9_\-]{20,}\b")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE)),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    (
        "db_connection_with_password",
        re.compile(r"\b(?:postgres|postgresql|mysql|mongodb)(?:\+srv)?://[^\s:@/]+:[^\s@/]{4,}@[^\s/]+", re.IGNORECASE),
    ),
    ("env_file_reference", re.compile(r"\b(?:\.env(?:\.[A-Za-z0-9_\-]+)?)\b")),
    ("credentials_json", re.compile(r"\bcredentials\.json\b")),
    ("secrets_yaml", re.compile(r"\bsecrets\.(?:yaml|yml)\b")),
]

_KV_ASSIGNMENT = re.compile(
    r"^\s*(?P<key>[A-Z][A-Z0-9_]{2,})\s*=\s*(?P<val>\S+)\s*$",
)

# Common placeholder tokens used in fixtures / templates
_PLACEHOLDER_TOKENS = {
    "",
    "changeme",
    "your_api_key_here",
    "your-key-here",
    "your_key",
    "xxx",
    "xxxx",
    "xxxxx",
    "placeholder",
    "example",
    "todo",
    "secret",
    "password",
}


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def _line_range_for_span(content: str, start: int, end: int) -> tuple[int, int]:
    start_line = content.count("\n", 0, start) + 1
    end_line = content.count("\n", 0, end) + 1
    return (start_line, end_line)


def scan(content: str, channel: str = "artifact") -> list[SecretMatch]:
    """Return structural matches for ``content``. Never returns the matched string."""
    matches: list[SecretMatch] = []
    seen: set[tuple[str, int, int]] = set()

    for name, pattern in _PATTERNS:
        for m in pattern.finditer(content):
            line_range = _line_range_for_span(content, m.start(), m.end())
            key = (name, line_range[0], line_range[1])
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                SecretMatch(pattern_type=name, approx_line_range=line_range, channel=channel)
            )

    # Entropy-gated KEY=VALUE heuristic (suppresses placeholders / templates).
    for lineno, line in enumerate(content.splitlines(), start=1):
        m = _KV_ASSIGNMENT.match(line)
        if not m:
            continue
        val = m.group("val")
        lowered = val.lower()
        if lowered in _PLACEHOLDER_TOKENS:
            continue
        if len(val) < 20:
            continue
        if _shannon_entropy(val) < 3.5:
            continue
        key_name = m.group("key")
        if not any(tok in key_name for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS")):
            continue
        k = ("high_entropy_kv", lineno, lineno)
        if k in seen:
            continue
        seen.add(k)
        matches.append(
            SecretMatch(
                pattern_type="high_entropy_kv",
                approx_line_range=(lineno, lineno),
                channel=channel,
            )
        )

    return matches


def redact(content: str, matches: list[SecretMatch]) -> str:
    """Replace matched spans with stable placeholders.

    Because ``scan`` doesn't preserve the raw spans, we redact by re-running
    patterns. In-memory only — redaction mappings never persist.
    """
    redacted = content
    counter = 0
    for name, pattern in _PATTERNS:
        def _sub(m: re.Match[str]) -> str:  # noqa: ANN001
            nonlocal counter
            counter += 1
            return f"[REDACTED_{counter}]"

        redacted = pattern.sub(_sub, redacted)

    # Also redact high-entropy KV lines to be thorough.
    def _kv_sub(m: re.Match[str]) -> str:  # noqa: ANN001
        nonlocal counter
        val = m.group("val")
        lowered = val.lower()
        if lowered in _PLACEHOLDER_TOKENS or len(val) < 20 or _shannon_entropy(val) < 3.5:
            return m.group(0)
        key = m.group("key")
        if not any(tok in key for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS")):
            return m.group(0)
        counter += 1
        return f"{key}=[REDACTED_{counter}]"

    redacted = "\n".join(
        _KV_ASSIGNMENT.sub(_kv_sub, line) if _KV_ASSIGNMENT.match(line) else line
        for line in redacted.splitlines()
    )
    return redacted
