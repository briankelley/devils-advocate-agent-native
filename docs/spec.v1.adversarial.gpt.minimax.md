# Specification Enrichment Report

## Overview
Total suggestions: **33**  
Themes represented: **13**

Ideas independently suggested by **2+ reviewers** (strong priority signals) appear in: **Data Model, Features, Onboarding, Performance UX, Security Privacy**.

## Accessibility

### Screen-reader-friendly report conventions: Define report_markdown conventions for accessibility: stable heading structure, explicit severity words (no reliance on visuals), predictable phrasing for fixed vs deferred items, and bullet summaries alongside any tables. -- 1/2 reviewers  
(Description) Standardize `report_markdown` so it reads well in terminals and assistive tech: consistent heading levels, explicit severity wording, and predictable text patterns for “fixed vs deferred” items—plus bullet summaries next to any table-like structures.  
(Why it adds value) Makes the proof-of-thinking artifact usable across viewing modes, including screen readers, and reduces misinterpretation from purely visual formatting.

## Content

### Domain-specific agent workflow recipes: Ship a library of workflow recipes (schema migrations, auth changes, public API updates, risky refactors, implementation planning) describing when to invoke dvad, what context to pass, what focus tags to use, and how to present findings in handoff. -- 1/2 reviewers  
(Description) Add a curated set of “recipes” showing concrete invocation patterns for common engineering workflows: what triggers `/dvad`, what context fields to fill, recommended focus tags, and how to structure the handoff output for that domain.  
(Why it adds value) Reduces onboarding friction for both agents and humans by turning abstract “when/what” guidance into copyable, repeatable playbooks.

## Data Model

### Linked review lineage across iterations and reruns: Preserve review continuity across stateless invocations by linking related reviews. Add lineage fields such as parent_review_id (and optionally supersedes_review_id/artifact_hash) so a revised submission’s re-review can reference prior findings. -- 2/2 reviewers  
(Description) Introduce `parent_review_id` (optionally `supersedes_review_id`, `artifact_hash`) so each re-review can form a thread back to the original checkpoint, even though reviews remain stateless.  
(Why it adds value) Enables humans and downstream tooling to communicate iteration progress clearly (e.g., “iteration 2 of 3”), and to show what was fixed vs what is newly discovered.

### Rich review provenance and diversity metadata: Add richer provenance fields to the review response, including provider diversity score, models attempted/succeeded/failed, context files used, and a review signal rating. -- 1/2 reviewers  
(Description) Expand review response metadata with trust/coverage indicators: provider diversity score, which models ran and how they behaved, which context files were used, and a “review signal” quality rating.  
(Why it adds value) Helps the calling agent decide how much confidence to place in findings and enables clearer “degraded execution” explanations.

### Review history persistence with recurring-issue detection: Persist lightweight review history and surface patterns over time via a query tool (dvad_history). -- 1/2 reviewers  
(Description) Keep a small local history index keyed by `review_id` → summary metadata, and provide a `dvad_history`-style tool to query patterns like “rate-limiting issue caught 4 times.”  
(Why it adds value) Turns dvad from point-in-time review into team learning/institutional memory.

### Per-model contributor tracking in findings (model perspectives): Preserve how each model uniquely framed a finding by adding a model_perspectives field containing original phrasing from each model’s review before deduplication. -- 1/2 reviewers  
(Description) Add `model_perspectives` to capture each model’s original phrasing/stance for a finding, rather than only the deduped final version. The same area also suggests opt-in aggregation dashboards from persisted history.  
(Why it adds value) Improves human interpretability and creates a training signal for future rubric tuning and learning about how models disagree.

## Features

### Structured remediation & verification per finding: Extend each finding with concrete, agent-usable fix guidance (suggested action, suggested test, verification hint; optionally remediation). -- 2/2 reviewers  
(Description) For each finding, add structured fields like `suggested_action`, `suggested_test`, and `verification_hint` (and/or a `remediation` field during dedup).  
(Why it adds value) Converts “what’s wrong” into “how to fix and prove it,” making handoff immediately executable by the calling agent.

### Stage-aware checkpoint labeling: Let each review declare an explicit stage (plan, implementation, post-fix, pre-handoff) and include the stage in structured output and recommended handoff text. -- 1/2 reviewers  
(Description) Add a stage label to the review response and reflect it in the handoff text so the trail is easy to scan across the lifecycle.  
(Why it adds value) Improves readability and auditing when agents run multiple checkpoints.

### Focus-area tags beyond artifact type: Allow callers to supply structured focus tags (security, performance, migration_risk, backwards_compatibility, test_strategy, reliability, developer_experience). -- 1/2 reviewers  
(Description) Extend rubric selection via structured focus tags in addition to `artifact_type`.  
(Why it adds value) Lets agents narrow attention without needing custom rubric plumbing.

### Adaptive reviewer selection based on artifact domain: Recommend which available models best fit the artifact via lightweight heuristic classification (output a `recommended_reviewers` hint). -- 1/2 reviewers  
(Description) Use non-LLM heuristics (file extensions/keywords/import patterns) to choose more domain-suitable reviewers; emit `recommended_reviewers` in `dvad_config`.  
(Why it adds value) Improves quality while avoiding expensive classification model calls.

### Concurrent review with graceful partial failure behavior: Define deterministic behavior when reviewer models fail mid-review. -- 1/2 reviewers  
(Description) Specify behavior such that if ≥2 reviewers succeed, proceed with dedup on successful outputs and return `reviewer_errors`; otherwise abort (optionally with partial findings).  
(Why it adds value) Makes the tool reliable and predictable under partial provider outages.

### Review intensity dial (fast/standard/deep): Add an intensity parameter controlling review depth and cost tradeoffs. -- 1/2 reviewers  
(Description) Introduce `intensity` tiers (fast/standard/deep) that map to reviewer count and dedup passes, tied to documented cost envelopes.  
(Why it adds value) Gives agents a simple, explicit quality/cost control lever beyond the budget cap.

### Artifact chunking / triviality handling: Define chunking for large inputs and/or add a tool to decide when to skip trivial changes (dvad_check_triviality). -- 1/2 reviewers  
(Description) Ensure deterministic handling of very large artifacts by chunking into logical segments and merging findings via dedup; additionally, optionally add a `dvad_check_triviality` tool so the agent can explicitly skip trivial diffs and report the decision in handoff.  
(Why it adds value) Prevents quality collapse on oversized inputs and improves budget efficiency with visible rationale for skipping.

## Integrations

### PR-ready and ADR-ready report variants: Provide alternate markdown renderings optimized for PRs, ADRs, release notes, and commit messages. -- 1/2 reviewers  
(Description) Output multiple markdown formats tailored to destinations: PR emphasis on fixed vs deferred items; ADR emphasis on assumptions/tradeoffs/unresolved risks.  
(Why it adds value) Increases “drop-in” usability across common engineering artifacts.

### Deferred-finding handoff to issue trackers (GitHub/Linear/TODO): Create issue/task-ready entries from deferred findings with severity, summary, and suggested owner wording. -- 1/2 reviewers  
(Description) Add an alternate output block to transform deferred findings into trackable tasks (GitHub issues, Linear tasks, TODOs).  
(Why it adds value) Keeps residual risk from being lost and reduces follow-up friction.

### Recommended MCP-to-MCP chaining patterns: Document dvad as a checkpoint node in MCP workflow graphs (git-mcp → dvad_review → github-mcp). -- 1/2 reviewers  
(Description) Provide explicit “wiring patterns” showing how dvad fits between other MCP servers without hardcoding integration code.  
(Why it adds value) Makes dvad easier to adopt as a composable component in larger agent toolchains.

## Monetization

### Team budget and usage reporting exports: Provide optional per-project/per-session usage summaries (spend, invocation count, durations, findings, model mix). -- 1/2 reviewers  
(Description) Add exportable local summaries for governance/justification: totals, averages, model mix, and spend.  
(Why it adds value) Helps teams track adoption and (even for local/byok setups) prepare for future policy/cost governance.

## Onboarding

### Guided first-run sample review flow: Demonstrate end-to-end dvad output on first run; show provider detection, estimate vs actual runtime, and a realistic handoff message (and offer a setup-required path). -- 2/2 reviewers  
(Description) Implement a “first-run experience” that immediately runs a demo review (or clearly returns a structured setup-required response). Include the observed outputs: provider detection, estimate, runtime, and example handoff.  
(Why it adds value) Proves value quickly and avoids user confusion during configuration.

### Automated “setup required” first-run response: On first invocation with no models.yaml and no API keys, return a structured setup-required response with a tutorial link (optionally run a demo when setup is valid). -- 1/2 reviewers  
(Description) When prerequisites aren’t met, return a structured non-fatal response explaining what’s missing and where to get help; if setup is present, optionally run a short demo.  
(Why it adds value) Converts installation/config errors into guided recovery instead of dead-end failures.

## Other

### Standardized degraded-review explanation section: Include a degraded_review section when reduced diversity, missing models, partial reviewer failure, or fallback dedup behavior occurs. -- 1/2 reviewers  
(Description) Add a consistent narrative block explaining what remains trustworthy and what caution to communicate to humans/agents.  
(Why it adds value) Prevents “silent degradation” and improves decision-making under imperfect execution.

## Performance Ux

### Progressive review updates and/or streaming partial results: Expose intermediate updates during review execution (reviewer started/completed, dedup running, report compiling). -- 2/2 reviewers  
(Description) Provide progress signals so users/agents aren’t stuck in “dead air” during tool execution.  
(Why it adds value) Improves perceived latency and makes it easier for agents to narrate what’s happening.

### Streaming partial results to reduce perceived latency: Support a streaming delivery mode where findings appear incrementally as each reviewer responds. -- 1/2 reviewers  
(Description) Allow partial findings to surface incrementally (while keeping the final JSON structure unchanged).  
(Why it adds value) Further reduces perceived delay and improves responsiveness during multi-model runs.

### Progressive progress signaling during a review + git-aware context injection (opt-in): Provide intermediate updates and optionally infer changed surfaces via git commands. -- 1/2 reviewers  
(Description) Pair “progress signaling” with an opt-in git-aware mode that can infer what changed (e.g., via `git diff`) to help the review use better context.  
(Why it adds value) Improves both UX responsiveness and context quality when the calling agent doesn’t supply a full artifact context window.

## Platform

### Capability negotiation via dvad_config flags: Add machine-readable capability flags for clients to adapt UX automatically. -- 1/2 reviewers  
(Description) Extend `dvad_config` with capability indicators like supports_estimate, supports_embedded_markdown, supports_progress_updates, supports_lineage_fields, etc.  
(Why it adds value) Avoids hardcoded assumptions and allows different MCP clients to provide consistent UX across versions.

### Capability probe for setup validation (dvad_validate): Add a tool that actively tests provider connectivity and reports latency/success/failure. -- 1/2 reviewers  
(Description) Implement `dvad_validate` to probe each detected provider with a minimal prompt, report latency, warn on API-key errors, and confirm token budgets.  
(Why it adds value) Turns “why doesn’t this work” into a deterministic diagnostic workflow.

### Hot-reload dvad config on change: Watch models.yaml/API key changes or expose dvad_reload with atomic validation. -- 1/2 reviewers  
(Description) Support reload without server restart; validation should be atomic (validate before committing) and should re-estimate available models.  
(Why it adds value) Smooths iterative setup and reduces operational friction.

### Docker packaging for frictionless installation: Provide a single Docker image with default models.yaml + env-var API key autodetect. -- 1/2 reviewers  
(Description) Offer container-first installation: `docker run ...` with environment variables providing API keys and minimal volume/config steps.  
(Why it adds value) Lowers adoption friction for developers who prefer container workflows.

## Security Privacy

### Sensitive artifact sanitization & redaction modes: Add configurable redaction modes and do-not-send controls; optionally use deterministic local reversible mappings so the LLM never sees secrets. -- 2/2 reviewers  
(Description) Add privacy controls like `redaction_mode`, `do_not_send_paths`, and `sensitivity_level`; implement a deterministic sanitization pass (e.g., redact API keys/PII) with optional local mapping.  
(Why it adds value) Enables safe review of production artifacts without forcing users to remove sensitive data manually.

### Local-only mode (air-gapped / no external model calls): Add local_only: true to route all review calls to locally hosted models and run dedup locally. -- 1/2 reviewers  
(Description) Provide a strict mode that uses locally hosted endpoints (Ollama/LM Studio/etc.) and keeps everything local, including dedup.  
(Why it adds value) Supports data residency requirements and “air-gapped” environments.

## Social

### Proof-of-thinking badges and handoff trailers: Add compact reusable snippets including review_id, model count, cost, and final pass status. -- 1/2 reviewers  
(Description) Define standard “trailers” (commit/PR footer/status line) that summarize dvad outcomes and make the adversarial checkpoint visible as a norm.  
(Why it adds value) Increases cultural adoption and provides auditability without adding UI complexity.

### Team-wide anonymized review statistics dashboard + severity-to-color contract: Generate local-only dashboards and define a stable severity→color mapping contract. -- 1/2 reviewers  
(Description) From persisted history, produce opt-in local metrics (categories, average cost, deferred frequency) and define a severity color contract (critical/high/medium/low) for future IDE integrations.  
(Why it adds value) Supports team learning and provides forward compatibility for v2 tooling.

## Ux

### Top-level review outcome classification (clean/caution/blocked/degraded): Return a simple control signal derived from severity mix, consensus strength, and model availability. -- 1/2 reviewers  
(Description) Add a high-level `outcome` classification so agents can decide whether to continue autonomously, re-run, or escalate to humans.  
(Why it adds value) Provides a stable, agent-friendly decision primitive rather than requiring complex interpretation of the full findings list.

### Agent invocation policy profiles (conservative/standard/paranoid): Introduce named policy profiles controlling when the Claude Code skill triggers dvad. -- 1/2 reviewers  
(Description) Provide named trigger policies (e.g., conservative triggers only for security/schema/deps; paranoid triggers more often).  
(Why it adds value) Gives users a simple mental model for automation boundaries and reduces “surprise” review runs.

## High-Consensus Ideas
- **Linked review lineage across iterations and reruns** (parent_review_id for continuity)  
- **Structured remediation & verification per finding** (suggested_action / suggested_test / verification_hint)  
- **Guided first-run sample review flow** (demo + setup-required structured recovery)  
- **Progressive review progress signaling during review execution**  
- **Sensitive artifact sanitization & redaction modes** (privacy-first review safety)