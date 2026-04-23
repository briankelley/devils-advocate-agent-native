# dvad Agent-Native Roadmap

**Last updated:** 2026-04-22
**Source:** Adversarial reviews of spec.v1 and spec.v2 (GPT-5.4 + MiniMax M2.7, Claude Opus 4.7 + Kimi K2.5, Claude Opus 4.7 + GLM-4, Claude Opus 4.7 + GPT-5.4)

Items below were raised during adversarial review, evaluated, and deferred — not because they're bad ideas, but because they don't belong in v1. Ordered roughly by perceived leverage.

---

## v2 — Post-launch, proven demand

### Structured remediation per finding
Extend each finding with `suggested_action`, `suggested_test`, `verification_hint`. Converts "what's wrong" into "how to fix and prove it." Deferred because it shifts the product surface from reviewer to fixer — a meaningful expansion that deserves its own design cycle.

### Local review analytics / telemetry dashboard
`dvad_stats` tool returning aggregate data: average cost, category trends, which findings humans accept vs dismiss. Proves ROI and enables rubric tuning. Requires persistence infrastructure that contradicts v1's stateless-first design.

### Focus tags beyond artifact type
Structured tags (`security`, `performance`, `migration_risk`, `backwards_compatibility`) that narrow rubric attention without custom rubric plumbing. Wait until built-in rubrics prove themselves.

### Review replay / reasoning transparency
`dvad_explain` tool: given a `review_id` and `finding_id`, return raw model outputs, dedup logic, and why the finding emerged. Trust-building feature — prove findings are useful before investing in explaining them.

### HTTP/SSE transport
Ship alongside stdio. Enables shared-service usage, remote dev environments, and CI workflows without local installs. Adds deployment complexity; wait for demand.

### PR-ready / ADR-ready report variants
Alternate markdown renderings optimized for PRs (emphasis on fixed vs deferred) and ADRs (emphasis on assumptions/tradeoffs/unresolved risks). Single `report_markdown` format needs to prove itself first.

### Deferred-finding handoff to issue trackers
Transform deferred findings into GitHub issues / Linear tasks / TODOs. Wrapper on top of the MCP primitive, not core product.

### Stage-aware checkpoint labeling
Explicit `stage` field in review response (`plan`, `implementation`, `post-fix`, `pre-handoff`). Useful for multi-checkpoint trails but the handoff format already implies stage via round labels.

### Structured delta for parent_review_id
When `parent_review_id` is provided and the parent review exists in local storage, compute a `delta` object: `new`, `resolved`, `persisting` findings via stable fingerprints. v1 ships `parent_review_id` as metadata linkage only; structured delta requires reading prior state, which tensions with stateless invocation. Add once persistence patterns are settled.

### Batch / multi-artifact review
`dvad_review_batch` accepting `artifacts[]` for cross-artifact consistency checking (plan + migration + spec in one call). Findings cite which artifact(s) they apply to. Reduces N× cost and improves cross-consistency. Adds real pipeline complexity; wait for demand.

### Finding location hints
Optional `file_path`, `span_label`, `approx_lines` per finding for mapping back to the caller's diff model. Useful for eventual IDE integration but adds response schema complexity without a v1 consumer.

### Additional artifact types (`migration`, `adr`)
Dedicated rubrics for schema migrations (reversibility, backfill, locking, deployment ordering) and architecture decision records (alternatives, consequences, blast radius on future decisions). Wait until the core artifact types prove the rubric pattern works.

### Dissent preservation
When only one model flags a high/critical issue and dedup would drop it, store in `dissent_findings` rather than losing the "outlier but right" signal. Interesting but adds response complexity; the current consensus model is simpler and should prove itself first.

### Agreement metric
Compute and expose `agreement_metric` (fraction with consensus ≥2 or similar). Low agreement becomes a meta-signal that the artifact is ambiguous. Interesting analytical feature, not v1.

---

## v3 — Ecosystem / team features

### Community rubric registry
Custom "rubric packs" (e.g., `HIPAA-compliance`, `crypto-correctness`) referenced by URI. Requires an ecosystem of users and use cases first.

### Repo-level policy triggers
`.dvad/policy.yaml` declaring which paths auto-invoke review, minimum consensus thresholds, required reviewers. Configuration-as-code for teams — requires teams using the product.

### Team dashboards / shareable gallery
`dvad_share` packaging sanitized review outputs as shareable HTML. Social/adoption feature for after the product proves useful to individuals.

### Interactive team calibration
`dvad_calibrate`: generate buggy samples, run reviews, learn team-specific thresholds. Enterprise onboarding — requires a team, a workflow, and an existing installation.

### Agent invocation policy profiles
Named trigger policies (`conservative`/`standard`/`paranoid`) controlling when the skill auto-invokes. Adds configuration layer; skill trigger conditions should be implicit first.

### `.dvad-ignore` content exclusion
Gitignore-style file for excluding sensitive content beyond secrets scanning (NDA code, PII in fixtures, proprietary logic). Enterprise adoption feature.

### Configurable severity thresholds for outcome classification
Make outcome rules tunable (e.g., treat `critical` as `caution` under certain team risk tolerances). Aligns checkpoint behavior with organizational risk appetite. Requires teams using the product first.

---

## Considered and rejected

These were raised during review and will not be implemented. Documented so they don't get re-raised.

| Suggestion | Reason rejected |
|---|---|
| Adversarial persona assignment (`persona_mix`) | Diversity comes from cross-provider model differences, not assigned roles. Adds prompt complexity without proven gain. |
| Temporal consensus decay / model freshness | Over-engineers consensus. Count is simple and interpretable; freshness weighting adds hidden complexity. |
| Author provenance / blind-spot calibration | Research direction, not product feature. Requires persistent profiling. |
| Multi-modal artifact review (URI + mime_type) | v1 is text-only. No value until multimodal review rubrics exist. |
| SARIF / LSP diagnostic export | v2 IDE territory. No value without an IDE consumer. |
| Docker packaging | Premature. pip/pipx is the right v1 distribution. |
| Hot-reload config | Over-engineered. Restart the server. |
| Emergency override / force_approve | dvad is a checkpoint, not a gate. Agents already skip and note it. |
| Machine-readable fix-it patches (`suggested_fix`) | Same as structured remediation — turns reviewer into fixer. |
| Epistemic status granularity (`certain`/`likely`/`speculative`) | Four severity levels + consensus count already captures confidence. |
| Tiered model selection presets (`quick`/`standard`/`thorough`) | One mode in v1. Tiers are premature until a second mode exists. |
| Context window smart truncation | Agent should chunk before calling dvad, not dvad internally. |
| Async background review jobs | Lite mode targets <30s. Background jobs solve a non-problem at this latency. |
| Capability negotiation flags | One mode, fixed capabilities. Negotiate when there's something to negotiate. |
| Plain-English summary mode | Audience is developers and agents. Non-expert summaries are v2. |
| `dvad_demo` fixture reviews | Requires maintaining canned responses. `setup_required` response is the v1 answer. |
| `dvad_doctor` / `dvad_validate` | Three config inputs (API keys). `dvad_config` reports availability; first review fails clearly on bad keys. |
| Adaptive reviewer selection | Hidden heuristic complexity. Let config choose models. |
| Per-model contributor tracking (`model_perspectives`) | Dedup collapses perspectives into findings by design. Raw perspectives add bulk without consumer. |
| Structured open questions with effort estimates | Over-structures the handoff. Agent presents deferred items with context already. |
| Proof-of-thinking badges / commit trailers | Cultural artifact for blog posts and READMEs, not product feature. |
| Screen-reader-friendly report conventions | `report_markdown` is standard markdown. Accessibility of the consuming UI is the consumer's job. |
| Prompt injection pre-scan | Multi-model adversarial design is itself the defense. Regex detection is trivially bypassed and false-positives on legitimate content. Not a security scanner. |
| Dedup merge confidence (`merge_confidence`) | Over-instruments dedup. If dedup collapses distinct issues, the fix is better dedup prompts, not confidence scores on bad merges. |
| Hallucination guard / meta-check | Adds latency and cost to guard against a failure mode that consensus already mitigates. One model hallucinating a bug gets low consensus. |
| Review-of-the-review auto-arbitration | Extra model call to arbitrate disagreements. The disagreement IS the signal; arbitrating it away defeats the purpose. |
| Namespaced env vars (`DVAD_ANTHROPIC_KEY`) | Over-engineers key management. Standard provider env vars are the convention; dvad-specific keys fragment the ecosystem. |
| Review caching by content hash | Premature optimization. Reviews are cheap (<$0.50) and artifacts change between calls. Cache invalidation is harder than re-running. |
| Reviewer model rotation across reviews | Budget rarely limits reviewer count in lite mode. If it does, that's a config decision, not an algorithm. |
| `dvad_should_review` heuristic tool | Skill definition already describes trigger conditions. A separate tool for "should I even bother" adds a decision point that should be implicit. |
| CI-discoverable output files | CI integration is explicitly v2. Writing files when `CI=true` is a half-measure. |
| Ledger format compatibility with dvad core | Separate products, separate schemas. Compatibility coupling defeats the standalone design. |
| Non-English artifact support (`language` param) | Reviewer models handle multilingual input natively. Adding a language parameter implies dvad does translation, which it doesn't. |
| Artifact type auto-detection | Trusting heuristics over explicit caller labels adds hidden complexity and ambiguity. The agent knows what it's submitting. |
| Debug mode exposing reviewer prompts | Prompts are implementation detail, not product surface. Exposing them creates a support burden and locks prompt format. |
| Cost-tiered model selection (`cost_tier`) | Same as rejected tiered presets. One mode, one tier. |
| Provider health canary before fan-out | Partial failure handling already covers this case. A canary adds latency to every call to save latency on rare failures. |
| MCP resource endpoints for review retrieval | Over-engineers persistence. Reviews persist to disk as files; agents can read files. |
| Severity floor rendering filter | Agents already filter findings programmatically. A server-side rendering filter adds a parameter for something the consumer controls. |
| Handoff visual tiers (compact/standard/detailed) | One handoff format that works. Tiered formatting is complexity for the sake of aesthetics. |
