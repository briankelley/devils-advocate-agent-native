# Specification Enrichment Report

## Overview
**Total suggestions:** 28  
**Themes represented:** 12  
**Independent cross-reviewer overlap:** 3 ideas were independently proposed by 2+ reviewers (all were **2/2** consensus).

The themes with the strongest signals are **Features**, **Platform**, and **Security Privacy**.

---

## Accessibility

### Accessible report output profiles (terse / narrative / structured) -- 1/2 reviewers  
Add multiple `output_format` styles tailored to accessibility needs (e.g., **`terse`** bullets-only, **`narrative`** prose flow, **`structured`** screen-reader optimized tables with ARIA/semantic structure). Also ensure `report_markdown` uses semantic headers and alt-text conventions so the “human handoff artifact” is accessible, not just readable.

### Plain-English “what this means for you” summary mode for non-experts -- 1/2 reviewers  
Introduce an `audience: "non_technical"` context flag that adds a simple “What this means for you” paragraph per critical/high finding, so PM/founders/compliance readers can understand implications without deciphering developer-oriented critique density.

---

## Content

### Community rubric registry with domain-specific modes via URI packs -- 1/2 reviewers  
Define a schema for **custom “rubric packs”** (e.g., `HIPAA-compliance`, `Crypto-correctness`) referenced by URI from `artifact_type`. An MCP server can download/cache these packs so specialized adversarial review doesn’t bloat the core package—enabling an ecosystem of published rubrics.

### `test` as a first-class artifact type with a dedicated test-quality rubric -- 1/2 reviewers  
Add `artifact_type: "test"` and a rubric specifically targeting common agent failure modes in tests: vacuous assertions, insufficient branch/negative coverage, over-mocking, and whether the test would actually catch the bug it claims to prevent. This is high-leverage because test-writing is where “fake completeness” is most tempting.

### Adversarial persona assignment per reviewer using `persona_mix` -- 1/2 reviewers  
Instead of identical review approaches per reviewer, assign **distinct adversarial personas** (security auditor, SRE paged at 3am, complexity-hating staff engineer) via a `persona_mix` option. This improves coverage diversity and naturally strengthens “disagreement-as-signal” output.

---

## Data Model

### Epistemic status granularity beyond binary severity -- 1/2 reviewers  
Extend finding classification with epistemic tags such as `certain`, `likely`, `suspicious`, and `speculative`, plus a `certainty` field. This supports better filtering (e.g., “severity>=high AND certainty>=likely”) while still preserving speculative leads that may be useful.

### Temporal consensus decay using model freshness -- 1/2 reviewers  
Adjust consensus weighting based on how recently models were updated/trained. If newer models disagree with older ones, weight newer ones more to avoid “consensus illusions” from stale patterns. Return `model_freshness` metadata in response.

### Author provenance and blind-spot calibration -- 1/2 reviewers  
Add `author_agent` into review context and build a calibration matrix over time to adjust reviewer/severity weighting based on known weaknesses of specific author agents. This personalizes adversarial coverage beyond treating all artifacts as equally risky.

---

## Features

### Stable finding identity + review diffs/regression tracking + suppression workflow -- 2/2 reviewers  
Add mechanisms to track findings across revisions:
- accept `previous_review_id` (or equivalent) and return a **`delta`** (new/resolved/persistent)
- use stable semantic anchors and/or a **`fingerprint`** hash to recognize the “same” finding even when line numbers shift
- provide a **human feedback loop** (e.g., mark false positives / accepted risk) to suppress noise over time
- add a focused **`dvad_rereview`** tool for post-fix verification and regression detection  
This directly improves “progress reporting,” reduces whack-a-mole, and makes iteration feel trustworthy.

### Hierarchical review inheritance / chain-of-custody for sub-agents -- 1/2 reviewers  
When a parent agent delegates to sub-agents, define how the parent should incorporate sub-agent review findings automatically into subsequent review context (e.g., `parent_review_chain`). This avoids redundant work while preserving evidence of what was already adversarially checked.

### Multi-modal artifact review extension via `artifact` URIs + `mime_type` -- 1/2 reviewers  
Future-proof the protocol by adding `mime_type` and allowing `artifact` as a URI reference. Even if v1 is text-focused, designing the extension point now enables later review of diagrams/UI mockups with the same MCP interface.

### Per-artifact-type severity calibration anchors -- 1/2 reviewers  
Document calibrated severity anchors per `artifact_type`, so “medium/high/critical” mean consistent things relative to that artifact domain. Include those anchors in reviewer prompts and return them so both humans and agents interpret severities correctly.

### First-class disagreements as an explicit output section (`dissensus as a finding`) -- 1/2 reviewers  
Add a `disagreements` section capturing cases where models significantly diverge (e.g., one flags critical, others are silent; severity gaps >= a threshold). This surfaces tension points for human judgment rather than masking them behind majority vote.

### Artifact-type auto-detection instead of trusting caller labels -- 1/2 reviewers  
Use heuristics to detect `artifact_type` (diff headers → `diff`, markdown structure → `spec`, AST-valid code → `code`, imperative steps → `plan`). If detected type conflicts with caller label, use detected type and note the override for better rubric fit.

---

## Integrations

### Git context auto-capture for diff reviews (commit msg, base branch, log, diff stats) -- 1/2 reviewers  
When `artifact_type=diff` and `repo_root` is provided, optionally capture git context (proposed commit message, base branch, recent log, `git diff --stat`) so reviewers can critique intent, risk, and pattern consistency rather than only raw diff content.

### Findings export compatible with LSP diagnostic schema + SARIF (`output_format: "sarif"`) -- 1/2 reviewers  
Add an export mode that produces **SARIF** (and/or LSP-compatible diagnostic structure) so IDE/third-party scanners can ingest dvad findings without re-parsing dvad-specific JSON. This makes the findings “portable” into existing tooling ecosystems.

---

## Monetization

### Tiered model selection via `depth` presets -- 1/2 reviewers  
Expose `depth` presets like `quick` / `standard` / `thorough`, each mapping to specific model/provider choices with approximate cost and reasoning effort. This helps users align review spend with task stakes and prevents the “all-or-nothing budget pressure” failure mode.

---

## Onboarding

### Interactive team calibration via `dvad_calibrate` (generate buggy samples, learn thresholds) -- 1/2 reviewers  
Provide a one-time interactive calibration tool where agents generate intentionally buggy samples, run reviews, and teach humans what dvad catches vs misses. Output a team-specific `dvad-preferences.yaml` with thresholds and preferences (e.g., ignore deprecation warnings).

### `dvad doctor` setup health-check tool -- 1/2 reviewers  
Add a `dvad_doctor` MCP tool and CLI equivalent that checks configuration health: key presence, model reachability, diversity scores, budget defaults, and a short “try it” canned review measuring latency/cost. This reduces “installed but nothing works” adoption killers.

### `dvad_demo` fixture reviews for zero-keys evaluation -- 1/2 reviewers  
Ship a demo mode that runs bundled flawed fixtures (using recorded responses or free-tier calls) so new users can see full output quickly after install, without configuring keys first.

---

## Performance Ux

### Deterministic/heuristic prescreen gates to avoid expensive reviews (`prescreen`) -- 1/2 reviewers  
Implement a staged pipeline:
1) fast cheap prescreen (regex/AST linters/heuristics)  
2) deterministic policy-as-code prefilter (hard fail or annotate)  
3) only then fan out expensive multi-LLM review  
Expose as a `prescreen`-style option so trivial changes get near-instant “all clear” and complex changes trigger deep review.

### Context window smart truncation with priority markers -- 1/2 reviewers  
When artifacts exceed context limits, truncate intelligently by preserving high-signal regions. Add optional `priority_markers` (line ranges or function names) so important security/API-contract/error-handling sections remain in-window.

### Asynchronous background review jobs (`background: true`) -- 1/2 reviewers  
Add `background: true` to return immediately with `review_job_id`. Provide polling (`dvad_status`) or callbacks. For low-risk tasks, keep flow fast; if background completes with critical issues, append follow-up safely.

### Chunking + map-reduce for large multi-file reviews -- 1/2 reviewers  
For oversized artifacts, split along natural boundaries (files/headings/function+class boundaries), review chunks in parallel, then run a second-pass integration/dedup to collapse findings and flag cross-chunk issues (e.g., callers not updated).

---

## Platform

### Local review analytics + efficacy telemetry dashboard (`dvad_stats`) -- 2/2 reviewers  
Add optional local persistence (e.g., SQLite + localhost HTML dashboard) tracking:
- average cost, category trends, velocity  
- which model/finding types humans accept  
- acceptance vs deferred/dismissed outcomes  
Expose aggregated stats via a `dvad_stats` query. This provides ROI proof and an evidence-based rubric tuning loop.

### HTTP/SSE transport option in addition to stdio -- 1/2 reviewers  
Ship HTTP/SSE transport alongside stdio early. This enables shared service usage, remote dev environments, and CI workflows without local installs—avoiding painful transport retrofits later.

---

## Security Privacy

### Secrets scanning, redaction, and privacy controls before external calls -- 2/2 reviewers  
Before sending artifacts to third-party LLMs:
- run secrets scanning (gitleaks-style)  
- abort or redact with stable placeholders (`[REDACTED_SECRET_<hash>]`)  
Add `privacy_mode` (`strict|permissive`) and `trust_level` hints (e.g., `"confidential"` restrict providers). Also return clear provenance about what content was shared with which providers. This is crucial for enterprise adoption.

---

## Social

### Shareable sanitized review-trail artifacts and gallery (`dvad_share`) -- 1/2 reviewers  
Add a `dvad_share` tool/flag that packages sanitized review outputs as self-contained HTML (optionally uploaded to a public-by-default gallery). This turns the handoff artifact into a shareable proof-of-value surface that can drive adoption and collaboration.

---

## Ux

### Review replay + reasoning transparency via `dvad_explain` -- 1/2 reviewers  
Add a `dvad_explain` tool that, given `review_id` and `finding_id`, returns debugging artifacts: raw model outputs, dedup/grouping logic, and why the finding emerged (consensus vs overzealous). This increases developer trust and reduces “why did it flag this?” friction.

### Emergency override with audited risk documentation (`force_approve`) -- 1/2 reviewers  
Add `force_approve` to bypass findings when paired with a `risk_acceptance_rationale`. Return a `bypassed` status, log the rationale immutably, and clearly mark “review bypassed” in the handoff so humans can audit and accept risk intentionally.

### Machine-readable fix-it suggestions with patches (`suggested_fix`) -- 1/2 reviewers  
Extend findings with optional `suggested_fix` including unified diff / structured patch representation (file path, line range, replacement text). This enables automated high-consensus low-risk fixes rather than only prose critique—turning dvad into a more productive collaborator.

### Streaming progress notifications during review -- 1/2 reviewers  
Emit MCP progress updates as each reviewer completes (timings and interim finding counts) instead of a long silent block. This improves UX and makes dvad feel like an active checkpoint.

### Repo-level policy triggers via `.dvad/policy.yaml` -- 1/2 reviewers  
Allow repositories to declare project-specific triggers and expectations (which paths auto-invoke review with which rubrics, minimum consensus thresholds, escalation categories, required reviewers). Implement via a `dvad_policy` tool or prompt injection so teams codify standards once.

### Structured “open questions” with resolution options + effort -- 1/2 reviewers  
Upgrade deferred items into decision-ready guidance by including for each open question: why it was deferred, concrete resolution options (accept risk/add test/refactor), and estimated effort per option. This transforms the handoff from “punted tasks” into a human decision briefing.

---

## High-Consensus Ideas
- **Stable finding identity + review diffs/regression tracking + suppression workflow** -- 2/2 reviewers  
- **Local review analytics + efficacy telemetry dashboard (`dvad_stats`)** -- 2/2 reviewers  
- **Secrets scanning, redaction, and privacy controls before external calls** -- 2/2 reviewers