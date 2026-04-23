# Specification Enrichment Report

## Overview
**Total suggestions:** 41  
**Themes represented:** 12  
**High cross-reviewer agreement (2+ reviewers):** 2 suggestions.  
Independently suggested by multiple reviewers:
- **Batch/multi-artifact review** (2/2)
- **Clarify “blocked vs advisory” semantics** (2/2)

---

## Accessibility

### Plain-text severity/consensus tags for better scannability in `report_markdown` -- 1/2 reviewers
Standardize **text-only** severity/consensus markers (e.g., `[CRITICAL][3/3]`) so summaries remain readable in **terminals/logs** and are more accessible to **screen readers**, without relying on color/icons or IDE styling.

### Non-English artifact support via `language` parameter -- 1/2 reviewers
Add a `language` parameter (e.g., `language: "en" | "auto" | ...`) so the rubric prompt and the reviewer output language are aligned to the **artifact’s language**, preventing confusing mixed-language handoffs (e.g., “bug in línea 42” coming from English-only rubrics).

---

## Content

### Add `migration` and `adr` as first-class artifact types -- 1/2 reviewers
Introduce new `artifact_type`s:
- `migration`: focus on reversibility, backfill, locking, deployment ordering
- `adr`: focus on alternatives, consequences, reversibility, blast radius on future decisions  
These are high-leverage shapes that prevent “plan/spec rubric mismatch” and reduce the chance teams burn by shipping migrations/architecture decisions unchallenged.

### PR/ticket comment templates embedding dvad reports -- 1/2 reviewers
Provide ready-made templates showing how agents can embed `report_markdown` into PR descriptions or issue comments (including a short dvad-lite header and collapsed report). This increases the likelihood that teams actually share the adversarial trail at the point humans review work.

### Minimal documented taxonomy for finding `category` -- 1/2 reviewers
Expand/clarify `category` into a small, documented taxonomy (e.g., correctness, security, performance, reliability, usability, testing, maintainability, docs). This enables consistent routing/aggregation without turning it into complex user-defined tagging.

---

## Data Model

### Stable finding fingerprints for cross-review delta tracking -- 1/2 reviewers
Add a stable fingerprint per finding derived from normalized issue text + category + affected location, distinct from `review_id`. With `parent_review_id`, compute finding status deltas like `resolved/persisting/new` so iteration changes are **machine-checkable** and crisp in the handoff.

### Return `artifact_hash` for caching and replay -- 1/2 reviewers
Return an `artifact_hash` (e.g., SHA-256 of normalized artifact text) in every response so callers can detect **unchanged re-review**, short-circuit redundant work, and build local caches keyed by `(artifact_hash, model_set, rubric_version)`.

### Finding location hints for easier mapping back to the caller’s diff model -- 1/2 reviewers
Augment each finding with optional location hints such as `file_path`, `span_label`, and `approx_lines` so callers can map/deduplicate findings against their own diff/context representation (even before IDE integration exists).

### Stable artifact and stage identifiers (`artifact_id`, `stage`) -- 1/2 reviewers
Allow optional `artifact_id` and `stage` identifiers (e.g., `plan_draft`, `impl_refactor`) in requests/responses so multi-round reviews correlate cleanly without overloading `project_name` or relying solely on `parent_review_id`.

### Structured deferred-items list separate from findings -- 1/2 reviewers
Add a first-class `deferred_items` array (e.g., `{finding_id, reason, requires_human, estimated_effort?}`) so deferred vs raised issues are cleanly separated and humans don’t need to infer it from handoff prose.

---

## Features

### Review-of-the-review meta-check for low-agreement cases (auto-arbitrate) -- 1/2 reviewers
When `agreement_metric` is very low (models sharply disagree), optionally invoke one extra model to arbitrate specifically about which findings are grounded in the artifact vs speculation. This adds one extra call only when needed.

### Agreement metric in every response + use it to detect ambiguity -- 1/2 reviewers
Compute and expose an `agreement_metric` (e.g., fraction with consensus ≥2, or Krippendorff-alpha on severity). Low agreement becomes an explicit meta-signal that the artifact or rubric fit is ambiguous/hard.

### Preserve high-stakes dissent as separate “outlier” findings (`dissent_findings`) -- 1/2 reviewers
If only one model flags a high/critical issue and dedup would drop/merge it, store it in `dissent_findings` rather than losing the “outlier but right” signal.

### Smart re-review with `acknowledge_findings` to pin accepted risk -- 1/2 reviewers
On `dvad_review` with `parent_review_id`, accept `acknowledge_findings: [finding_fingerprint]`. Reviewers should treat acknowledged items as intentionally not addressed and avoid re-raising the same issue.

### Scoped rubrics via `focus` flags (subset-based review passes) -- 1/2 reviewers
Add optional `focus` parameter to request only certain rubric parts (e.g., `["security","compatibility"]` or `["correctness"]`). Record which foci applied so results from multiple focused runs can be merged.

### Rubric “extension hooks” via additive `extra_checks` -- 1/2 reviewers
Add `extra_checks: string[]` to pass additive focus bullets (“pay special attention to row-locking semantics”) while keeping the built-in rubric as the anchor—avoiding full custom rubric complexity.

---

## Integrations

### Batch/multi-artifact review in one call (with cross-artifact findings) -- 2/2 reviewers
Add a batch mode (e.g., `dvad_review_batch` / `artifacts[]`) so models can reason over **related artifacts together** (plan + spec + migration, etc.). Findings should cite which artifact(s) they apply to, and dedup can run across the bundle—reducing N× cost and improving cross-consistency checking.

### Git-aware diff reviews with blame/history/test touch context -- 1/2 reviewers
For `artifact_type: "diff"` plus `repo_root`, optionally gather `git blame`, introducing commit(s), and tests touching changed symbols. Include this in reviewer context to improve regression reasoning.

### `dvad_should_review` cheap heuristic to decide whether to run review -- 1/2 reviewers
Provide a local, non-LLM `dvad_should_review` tool that returns `{should_review, reason, confidence}` so the agent can skip expensive reviews when changes are clearly irrelevant—without losing determinism or justification.

### CI-discoverable output files (`dvad-review.json` / `.md`) when `CI=true` or `$DVAD_OUTPUT_DIR` set -- 1/2 reviewers
Write `dvad-review.json` and `dvad-review.md` to a known directory under CI mode even if the MCP client doesn’t support persistence. This keeps v1 scope narrow while enabling trivial wrappers later.

### Minimal compatible `ledger.json` for downstream tooling -- 1/2 reviewers
When persisting local results, also emit a minimal `ledger.json` compatible with a subset of dvad core’s ledger format (`generate_ledger`). This helps external tooling correlate findings across CLI/MCP workflows without depending on dvad core.

---

## Monetization

### Cost-tiered model selection (`cost_tier`) -- 1/2 reviewers
Add `cost_tier: "economy"|"balanced"|"premium"` mapping to model subsets so the system can right-size review cost to artifact importance, while defaulting to the existing balanced behavior.

---

## Onboarding

### Install-time sample review via a canned self-test fixture -- 1/2 reviewers
After install, run a built-in self-test on a small diff with known flaws using the user’s configured models, producing real output in ~20s. This validates keys/models/dedup/cost tracking end-to-end and gives immediate user confidence.

### First-success narrative in Claude Code skill (guided tour) -- 1/2 reviewers
On the first successful `dvad_review` call per session, briefly explain the handoff structure (meaning of `outcome`, severity/consensus interaction, where markdown report lives, cost behavior). After that, revert to terse format.

### Config health hints in `dvad_config` for immediate setup quality feedback -- 1/2 reviewers
Extend `dvad_config` with a compact `hints` array describing config diversity/coverage health (e.g., provider/model diversity high vs limited). This helps users understand “how good” adversarial coverage likely is without parsing raw model lists.

---

## Performance Ux

### Structured budget/context-limit error guidance for re-chunking -- 1/2 reviewers
When reviews abort due to context limits or `budget_limit`, return structured guidance (e.g., `recommended_max_tokens_per_call`, `approx_artifact_tokens`, `suggested_chunking_strategy`) so agents can automatically re-chunk instead of guessing.

### Phase-based progress milestones (secrets_scan → fanout → dedup → summarization) -- 1/2 reviewers
Make progress updates semantic by including a `phase` field (and optional percentages) so clients can show meaningful status like `dedup` rather than opaque “percent complete”.

---

## Platform

### MCP resource endpoint for last-review retrieval -- 1/2 reviewers
Expose last N reviews as MCP **resources** (URIs like `dvad://reviews/{review_id}` or `dvad://reviews/latest`) so agents and humans can reference past review outputs without rerunning dvad.

### Named channels/streams in `context` for grouping reviews -- 1/2 reviewers
Support optional `channel`/`stream` identifiers in `context` (e.g., `feature/checkout`, `incident/1234`) and echo them in responses/persisted files, enabling tooling to group review checkpoints along meaningful axes.

---

## Security Privacy

### Don’t write full artifacts to disk by default -- 1/2 reviewers
Persist findings/review metadata by default but exclude full artifact content from disk. Store only `artifact_hash`, `artifact_type`, and token count; add `persist_artifact: true` for explicit opt-in. This supports enterprise/privacy concerns.

### Configurable secrets sensitivity profiles (`sensitivity_profile`) -- 1/2 reviewers
Add `sensitivity_profile` (relaxed/standard/strict) to tune secrets scanning behavior without per-provider complexity. Include the chosen profile in the response so agents/users understand why scans aborted or redacted.

### Safe-project labeling/reminders via `data_sensitivity` context -- 1/2 reviewers
Add optional `data_sensitivity` in `context` (public/internal/confidential). Echo it back and optionally confirm in `report_markdown` that secrets scanning ran and no obvious secrets were transmitted (or that review aborted), giving positive privacy guardrails confirmation.

---

## Social

### Handoff visual tiers that degrade gracefully -- 1/2 reviewers
Define three handoff formats:
1) ultra-compact one-liner for trivial reviews  
2) structured trail for typical reviews  
3) expandable detail with per-reviewer quotes when critical findings exist  
So output volume scales with severity and isn’t overwhelming.

---

## Ux

### Stream structured `partial_finding` events before dedup -- 1/2 reviewers
Emit structured `partial_finding` events as reviewer models complete (before dedup) so harnesses can begin acting on findings in real time for long-running flows; fall back to batch if streaming isn’t available.

### Configurable severity floor for compact output -- 1/2 reviewers
Add `severity_floor` that is a rendering filter only: findings below threshold are counted in `summary` but excluded from main `findings`/markdown. Models still review everything server-side for consensus counting.

### Optional per-model raw outputs (`include_reviewer_raw`) -- 1/2 reviewers
Add `include_reviewer_raw: true` to optionally return each model’s raw outputs alongside deduped findings. This improves transparency for calibration/coverage assessment, while keeping default output lean.

### Clarify “blocked vs advisory” semantics (checkpoint, not gate) -- 2/2 reviewers
Reinforce that dvad is an **adversarial checkpoint** rather than a hard shipping gate. Add an explicit `advisory: true` flag and document that `outcome: "blocked"` means “critical issues found” (not “agent must stop”). Pair with consistent skill behavior branches for each outcome.

### Prompt-injection pre-scan alongside secrets scanning -- 1/2 reviewers
Perform a prompt-injection pre-scan on the same hook as secrets scanning, flagging injection patterns (ignore previous instructions, embedded role markers, fake tool-call syntax, zero-width characters). Behavior should be abort/warn/neutralize similar to secrets handling.

### `highlighted_findings` fast subset for triage -- 1/2 reviewers
Add a top-level `highlighted_findings` slice (e.g., critical/high with consensus ≥2) as a convenience to avoid re-implementing filtering logic across agents and to make “what to address first” obvious.

### Multi-agent delegation guidance to keep one coherent adversarial trail -- 1/2 reviewers
Add skill documentation guidance for multi-agent workflows: the orchestrating agent owns the main “stage” checkpoints (plan and final implementation), while sub-agents may run internal checks but shouldn’t overwrite the main adversarial narrative.

---

## High-Consensus Ideas
- **Batch/multi-artifact review in one call (with cross-artifact findings)** -- *2/2 reviewers*  
- **Clarify “blocked vs advisory” semantics (checkpoint, not gate)** -- *2/2 reviewers*