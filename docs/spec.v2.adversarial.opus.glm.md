# Specification Enrichment Report

## Overview
**Total suggestions:** 34  
**Themes represented:** 11  

**Independent multi-reviewer overlap:** 1 suggestion is explicitly **high-consensus (2/2)**. Additionally, a few ideas appear duplicated across separate suggestion groups (e.g., *setup_required demo artifact* and *category breakdown in summaries*), which may indicate consolidation opportunities even when each group’s “consensus” counter is only 1/2.

---

## Content

### Per-artifact-type example findings in the skill definition (calibration examples) -- 1/2 reviewers
Add **2–3 concrete example findings per artifact type** to the Claude Code skill docs so agents can calibrate expected severity and formatting. This helps prevent over-weighting mediums, and reduces “malformed/no-specificity” low-signal findings.  
**Note:** the included details in this suggestion group focus on **rotating reviewer model combinations** (coverage diversity) rather than the example-calibration portion, so it may be worth merging/fixing the intent if the author treats these as related but distinct ideas.

---

## Data Model

### Closed enum taxonomy for finding categories (+ other/category_detail) -- 1/2 reviewers
Define `finding.category` as a **closed enum** (e.g., correctness/security/performance/…) and **normalize** reviewer output into it during dedup/normalization. Add an `other` bucket plus `category_detail` for outliers.  
**Why:** enables reliable filtering and aggregation; avoids category drift like `"security"` vs `"vulnerability"` breaking agent logic.

### Cross-review delta object for parent_review_id -- 1/2 reviewers
When `parent_review_id` is provided, include a first-class **`delta` object** such as `new`, `resolved`, `persisting`, `escalated` so iteration progress isn’t inferred by diffing findings arrays.  
**Why:** makes round-to-round tracking robust and simple for agents.

### Dedup merge confidence on merged findings (`merge_confidence`) -- 1/2 reviewers
When dedup merges multiple reviewer findings, include `merge_confidence` (e.g., `high/medium/low`) or an explicit linkage so agents/humans know when dedup may have collapsed distinct issues.  
**Why:** reduces the risk that aggressive merging hides genuine “same area, different bug” disagreements.

---

## Features

### Multi-file artifact bundles (`artifacts[]` with path/content/role) -- 1/2 reviewers
Replace/augment the single-string `artifact` with `artifacts: [{path, content, role}]` to support cohesive **cross-file** review and precise location references.  
**Why:** reviewers can treat primary vs context/test files differently and findings can point to real file paths.

### Artifact type auto-detection + validation against content -- 1/2 reviewers
Allow `artifact_type` to be omitted by **inferring type from content**, and when provided, **validate** it (warn if it doesn’t match content structure).  
**Why:** reduces integration friction for agents and catches rubric misapplication.

### Token budget/response size estimates in `dvad_estimate` -- 1/2 reviewers
Extend `dvad_estimate` to include `estimated_response_tokens` and `artifact_tokens`.  
**Why:** context-constrained agents can decide whether to trim/split before calling, especially for large `report_markdown`.

### Rubric dimensions checklist in the review response (`rubric_evaluated`) -- 1/2 reviewers
Add a `rubric_evaluated` array showing which rubric dimensions were checked and their outcomes (including model counts / related finding IDs when relevant).  
**Why:** a “clean” result becomes interpretable: it distinguishes “checked and found none” from “never looked.”

### Reviewer model agreement/disagreement map (`model_agreement`) -- 1/2 reviewers
Add a meta-section mapping where models **agreed vs disagreed** across rubric dimensions, including explicit “split” decisions.  
**Why:** helps humans focus on ambiguity areas even when merged findings are low-consensus.

### Configurable severity thresholds for outcome classification -- 1/2 reviewers
Make `outcome` rules configurable (e.g., treat `critical` as `caution` under certain team risk tolerances) using thresholds over severity + consensus.  
**Why:** aligns the checkpoint behavior with organizational risk appetite and prevents alert fatigue.

### Debug mode exposing exact reviewer prompts (`debug` → prompts sent) -- 1/2 reviewers
Add a `debug` boolean so the response can include the actual prompts sent to each reviewer model.  
**Why:** improves transparency and enables prompt/rubric troubleshooting.

### Review scope focusing via `focus_regions` / inline focus tags -- 1/2 reviewers
Allow agents to annotate risky regions (diff line ranges or tags like `[DVAD:FOCUS security]...`) so reviewers weight attention appropriately.  
**Why:** large diffs frequently contain one risky core; without focus, reviewers waste attention and may miss subtle issues.

### Review-result caching keyed by content hashing (`cache_hit`) -- 1/2 reviewers
Cache `dvad_review` results keyed by artifact hash (plus instructions hash) within server lifetime and return `cache_hit: true`.  
**Why:** prevents redundant cost for re-reviews of unchanged content.

### Project-local config via `.dvad/agents.yaml` -- 1/2 reviewers
Support a repo-root `.dvad/agents.yaml` with team-shared overrides (models, budgets, rubric additions, auto-trigger patterns).  
**Why:** gives consistent behavior across team members without hosted services.

### Lightweight hallucination guard before final dedup -- 1/2 reviewers
After collecting findings but before dedup, run a cheap meta-check that flags findings referencing behavior not present in the artifact; mark them `confidence: "low"` rather than deleting.  
**Why:** mitigates “invented bugs” failure modes without large added latency/cost.

### Namespaced environment variables for project-scoped API keys -- 1/2 reviewers
Support `DVAD_ANTHROPIC_KEY`, `DVAD_OPENAI_KEY`, etc. with precedence over global provider keys.  
**Why:** enables separate billing/budget control for review tooling.

### Artifact size pre-check with chunking guidance (`artifact_too_large`) -- 1/2 reviewers
Before fan-out, estimate artifact token count; if above threshold, return `artifact_too_large` with recommended chunking guidance (and instruct agent to re-run per chunk).  
**Why:** avoids truncation-driven shallow reviews.

### Reviewer model rotation for coverage diversity (across reviews) -- 1/2 reviewers
When multiple models are available but budget limits reviewers, rotate model combinations across reviews and track which combinations were used (in-memory).  
**Why:** prevents the human from repeatedly seeing the same pair of perspectives.

### Finding category breakdown in summary for pattern recognition (`by_category`) -- 1/2 reviewers
Add `summary.by_category` counts (in addition to severity counts).  
**Why:** enables agents/humans to detect recurring issue patterns across iterations.

### Category breakdown in summary for pattern recognition (`by_category`) -- 1/2 reviewers
Same idea as above, but phrased as a dedicated summary improvement: include counts per category to support pattern detection.  
**Why:** enhances triage and systemic risk detection.

---

## Integrations

### Git-aware diff generation from working tree (`git_diff`) -- 1/2 reviewers
Add optional `git_diff` input (e.g., `main..HEAD`, `staged`) so dvad generates the diff from `repo_root`.  
**Why:** reduces formatting/truncation errors from agent-constructed diffs.

### Git-aware context hints in skill definition (pass git metadata into `context.instructions`) -- 1/2 reviewers
Instruct the Claude Code skill to pass structured git metadata (recent `git log`, `diff --stat`, branch name) into `context.instructions`.  
**Why:** improves reviewer calibration (new code vs mature module; expected maturity/testing risk).

### Formal JSON schema for the handoff adversarial trail -- 1/2 reviewers
Provide a machine-parseable JSON schema alongside human-readable handoff text for the adversarial trail (review_id, stages, findings fields, final_pass, open_questions, etc.).  
**Why:** unlocks tooling (bots, IDE extensions, dashboards) without brittle regex parsing.

---

## Onboarding

### First-run guidance embedded as inline annotations (`first_run_guidance`) -- 1/2 reviewers
Add a `first_run_guidance` field on initial response explaining how to interpret consensus, severity+consensus, `degraded`, and how to present findings. Omit it after first run in session.  
**Why:** reduces “how do I read dvad output?” onboarding friction and improves handoff quality immediately.

### Guided first-review walkthrough with demo artifact in `setup_required` -- 1/2 reviewers
Enhance `setup_required` to include `demo_artifact` and `demo_expected_findings` so the agent can demonstrate dvad value without any API calls.  
**Why:** turns installation/setup into a compelling product demo and reduces confusion.

---

## Other

### Parent-linked differential re-review with structured delta + stable finding lineage -- 2/2 reviewers
When `parent_review_id` is provided, do a **differential (non-blind) re-review** that evaluates whether prior findings were addressed, and return structured cross-round `delta` (`new/resolved/persisting/escalated`) plus **stable finding IDs** (`finding_id`/`lineage_id`).  
**Why:** makes iteration tracking reliable (no fragile array diffs), reduces duplicated re-discovery work, and enables clear statements like “persists from round 1 → resolved in round 3.”

### Known-issues seeding + finding-level dismiss reasons -- 1/2 reviewers
Add `known_issues` (fed into reviewer prompts) to prevent re-reporting already-known items unless materially new info appears, and require `dismiss_reason` annotations for deferred/out-of-scope findings that can seed future known-issues.  
**Why:** improves reviewer signal-to-noise, and gives humans a reasoned explanation instead of ambiguous “deferred.”

---

## Performance Ux

### Optional streaming of partial findings while reviewers run (`stream_partial`) -- 1/2 reviewers
Add `stream_partial: true` to stream individual reviewer findings as each model completes (before dedup), enabling earlier handling of high-severity issues.  
**Why:** improves responsiveness for slow models while keeping the final deduped output authoritative.

---

## Platform

### Commit trailer embedding for review provenance (`dvad-review:`) -- 1/2 reviewers
Add a machine-parseable `commit_trailer` string suitable for git commit messages.  
**Why:** allows CI/auditing tooling to query adversarial review provenance directly via `git log` without extra infrastructure.

---

## Security Privacy

### Enterprise content governance via `.dvad-ignore` -- 1/2 reviewers
Support a gitignore-like `.dvad-ignore` to redact/exclude sensitive content beyond basic secrets scanning (NDA code, PII in fixtures, proprietary logic).  
**Why:** enterprise adoption often fails due to “what gets sent to external LLMs,” not just “secrets.”

---

## Social

### Shareable review permalink (self-contained HTML) -- 1/2 reviewers
When persisting reviews, generate a standalone HTML file containing findings, model agreement visualization, and iteration history.  
**Why:** enables async review sharing for PR reviewers/security teams without server-side hosting.

---

## Ux

### Handoff formatting tool for non-Claude MCP clients (`dvad_format_handoff`) -- 1/2 reviewers
Provide a `dvad_format_handoff` tool that converts a review response + task summary into the recommended handoff text.  
**Why:** moves handoff formatting from “skill behavior” into an ecosystem-wide contract.

### Explicit “clean bill of health” positive signals (`positive_signals`) -- 1/2 reviewers
When `outcome` is `clean`, include a `positive_signals` array describing explicit reviewer affirmations (with consensus counts).  
**Why:** “no findings” currently reads like “nothing happened,” undermining trust.

### Session-level review plan tool (`dvad_plan_session`) for multi-checkpoint tasks -- 1/2 reviewers
Add a tool that returns a recommended checkpoint strategy (e.g., plan → diff → tests), total budget, and how context should carry forward.  
**Why:** helps agents plan complex work coherently rather than invoking dvad ad-hoc.

### Skill disable toggle to pause auto-trigger behavior (`DVAD_AUTO_CHECKPOINT=false` / config) -- 1/2 reviewers
Add a mechanism to disable auto-triggering while keeping manual invocation available.  
**Why:** supports hotfix/demo/budget-tight situations without uninstalling.

### Provider health canary before fan-out -- 1/2 reviewers
Perform a lightweight canary call (to dedup/relevant endpoint) to detect likely provider issues early and optionally skip likely-failed providers; expose `last_provider_errors`.  
**Why:** reduces wasted timeouts and improves robustness during partial outages.

---

## High-Consensus Ideas
- **Parent-linked differential re-review with structured delta + stable finding lineage** (2/2 reviewers)