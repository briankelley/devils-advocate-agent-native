"""Rubrics per artifact type, dedup prompt. Inline strings, not templates.

No governance, no author response, no rebuttal rounds — this is lite mode.
Rubrics are adversarial by design: "attack this, don't cheerlead."
"""

from __future__ import annotations

ARTIFACT_TYPES = ("plan", "spec", "diff", "code", "decision", "test")


REVIEWER_SYSTEM = """\
You are an adversarial reviewer. Your job is to attack the artifact — find
flaws, gaps, wrong assumptions, missing failure modes, unstated risks. You
are not here to cheerlead.

Return STRICT JSON ONLY. No prose before or after. The response must be a
single JSON object matching:

{
  "findings": [
    {
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "category": one of [correctness, security, performance, reliability, testing, maintainability, compatibility, documentation, other],
      "issue": "<short one-line summary>",
      "detail": "<1-3 sentences of specifics — what exactly is wrong / missing / risky>"
    }
  ]
}

If you find nothing worth raising, return {"findings": []}. Do not invent
concerns to pad the list.
"""


_RUBRICS: dict[str, str] = {
    "plan": """\
Attack this PLAN on:
- Correctness of assumptions (what's being taken for granted?)
- Scaling & ops realities (what breaks under real load or real deployment topology?)
- Data integrity & concurrency (race conditions, consistency, idempotency)
- Failure modes explicitly unspecified
- Scope creep or missing non-goals
- Security implications (auth, secrets, injection, PII)
- Testability — would you know if it broke?
""",
    "spec": """\
Attack this SPECIFICATION on:
- Internal consistency (contradictions, ambiguities)
- Missing capabilities the named audience would expect
- Non-goals not explicit enough to prevent scope creep
- Over-engineering vs. under-engineering
- Open questions that are actually hidden design decisions
- Interfaces / contracts that would be painful to evolve
""",
    "diff": """\
Attack this DIFF on:
- Correctness bugs introduced or not caught
- Race conditions, off-by-ones, null/empty edge cases
- Security (input validation, injection, auth, secrets exposure)
- Performance regressions (N+1 queries, accidental quadratic behavior)
- Missing test coverage for the paths changed
- Breaks to backward compatibility
- Error handling gaps
""",
    "code": """\
Attack this CODE on:
- Correctness (edge cases, off-by-ones, empty/null, concurrent access)
- Security (input validation, injection, auth, secrets, unsafe deserialization)
- Reliability (error paths, resource leaks, timeouts)
- Performance (algorithmic complexity, hot paths, I/O patterns)
- Testability
- Maintainability red flags
""",
    "decision": """\
Attack this DECISION on:
- Unstated alternatives that may be better
- Load-bearing assumptions not called out
- Reversibility — how expensive is a wrong call here?
- Second-order effects
- Who bears the cost if this is wrong, and are they in the loop?
""",
    "test": """\
Attack this TEST SUITE on:
- Vacuous assertions (asserts that pass regardless of implementation)
- Over-mocking that decouples test from real behavior
- False-completeness (100% line coverage with 0% branch/path coverage)
- Happy-path-only scenarios with no failure or boundary tests
- Flaky or order-dependent tests
- Tests that won't catch the regression they claim to guard against
""",
}


def build_reviewer_user_prompt(
    artifact: str,
    artifact_type: str,
    instructions: str | None,
    reference_files: list[tuple[str, str]] | None,
) -> str:
    """Assemble the reviewer user prompt.

    reference_files is a list of ``(relative_path, content)`` tuples — the
    concatenated payload is what gets scanned for secrets before being sent.
    """
    if artifact_type not in ARTIFACT_TYPES:
        artifact_type = "plan"

    parts: list[str] = []
    parts.append(_RUBRICS[artifact_type])
    if instructions:
        parts.append("=== INSTRUCTIONS FROM CALLER ===")
        parts.append(instructions.strip())
        parts.append("=== END INSTRUCTIONS ===")
    parts.append("")
    parts.append(f"=== ARTIFACT ({artifact_type.upper()}) ===")
    parts.append(artifact)
    parts.append(f"=== END ARTIFACT ===")

    if reference_files:
        for path, content in reference_files:
            parts.append("")
            parts.append(f"=== REFERENCE FILE: {path} ===")
            parts.append(content)
            parts.append("=== END REFERENCE FILE ===")

    parts.append("")
    parts.append("Return STRICT JSON ONLY matching the schema in your system prompt.")
    return "\n".join(parts)


DEDUP_SYSTEM = """\
You consolidate adversarial review findings from multiple reviewers. Merge
findings that describe the same underlying issue; keep distinct findings
separate. You are STRICT:

- Two findings describing the same root issue = ONE merged finding.
- Same category + overlapping content + same affected surface = merge.
- Same keyword but different root cause = DO NOT merge.

Return STRICT JSON ONLY with this shape:

{
  "findings": [
    {
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "category": one of [correctness, security, performance, reliability, testing, maintainability, compatibility, documentation, other],
      "issue": "<short one-line summary>",
      "detail": "<1-3 sentences merged from contributors>",
      "source_indices": [<int>, ...]  // indexes from the raw list below that contributed
    }
  ]
}
"""


def build_dedup_user_prompt(raw_findings: list[dict]) -> str:
    """Format the reviewer-produced findings for dedup input."""
    lines: list[str] = []
    for i, f in enumerate(raw_findings):
        lines.append(f"FINDING {i}:")
        lines.append(f"  REVIEWER: {f.get('reviewer', '?')}")
        lines.append(f"  SEVERITY: {f.get('severity', 'medium')}")
        lines.append(f"  CATEGORY: {f.get('category', 'other')}")
        lines.append(f"  ISSUE: {f.get('issue', '')}")
        if f.get("detail"):
            lines.append(f"  DETAIL: {f['detail']}")
        lines.append("")

    return (
        "Consolidate the following findings. Return STRICT JSON per the schema "
        "in your system prompt. Each ``source_indices`` entry must reference the "
        "FINDING N numbers below.\n\n"
        + "\n".join(lines)
    )
