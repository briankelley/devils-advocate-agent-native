# dvad v1 Agent-Native Spec

**Status:** Final draft — ready for implementation planning
**Date:** 2026-04-22
**Author:** Brian Kelley + Claude (strategic conversation, not generated slop)
**Review history:**
- spec.v1.md → reviewed by GPT-5.4 + MiniMax M2.7 (33 suggestions), Claude Opus 4.7 + Kimi K2.5 (28 suggestions)
- spec.v2.md → reviewed by Claude Opus 4.7 + GLM-4 (34 suggestions), Claude Opus 4.7 + GPT-5.4 (41 suggestions)
- 10 findings incorporated across two rounds; remainder triaged in Prior Review Dispositions

---

## Context

dvad (Devil's Advocate) is a working multi-LLM adversarial review tool. It pits models from different providers against each other to find flaws in plans, code, and specifications before they ship. The underlying engine — provider abstraction, deduplication, normalization, revision, governance — is mature, tested (~1,773 tests), and battle-proven.

The problem: dvad is invisible. It requires manual CLI invocation or a complex GUI and configuration to manage, human-curated input files, a configured `models.yaml`, and a human who remembers to run it. In an ecosystem where developers work through AI agents (Claude Code, Cursor, Codex), dvad sits outside the flow. No agent can call it. No developer discovers it in their tool harness.

Meanwhile, no one is shipping multi-provider adversarial review as an agent-callable checkpoint. Single-model review tools exist (CodeRabbit, Greptile). Multi-agent task frameworks exist (AutoGen, CrewAI). But the specific combination — adversarial review from multiple providers, integrated at the agent's "done" boundary, producing a proof-of-thinking artifact — has no shipped product.

This spec defines dvad v1 agent-native: the minimum surface needed to make adversarial review a tool any AI agent can call, any developer can discover in their harness, and no one would ship without once they've seen the output.

---

## Product Definition

dvad v1 agent-native is a **standalone product** — architecturally independent from dvad core. It shares conceptual DNA and adversarial review methodology with dvad, but carries no dependency on the dvad CLI, GUI, or full review pipeline. The codebase is intentionally small, focused, and readable in 10 minutes.

It ships two things:

1. **An MCP server** that exposes adversarial review as tool calls any MCP-compatible client can invoke (Claude Code, Cursor, VS Code, Codex, custom harnesses).
2. **A Claude Code skill** (`/dvad`) that teaches agents *when* and *how* to invoke adversarial review and how to present findings in their handoff to the human.

Provider patterns and dedup rubrics may be ported from dvad core where they fit cleanly; the full dvad pipeline is not a dependency.

---

## Target Users

**Primary:** Developers using AI coding agents (Claude Code, Cursor, Codex) who want higher-confidence output from their agents. They don't invoke dvad directly — their agent does.

**Secondary:** Developers who install the MCP server or plugin and configure their agent harness to use it. Power users who already know dvad and want agent integration.

**Not v1:** Developers who want IDE-native inline diagnostics (gutter annotations, squigglies). That's v2.

---

## Core Concept: The Adversarial Checkpoint

dvad v1 introduces a new primitive to agent workflows: the **adversarial checkpoint**. This is a point in the agent's task lifecycle where it pauses, submits its work to multiple independent models for adversarial review, processes the disagreements, and includes the trail in its handoff message.

The checkpoint is NOT a human decision. The agent invokes it automatically based on task characteristics (non-trivial implementation, schema changes, architectural decisions). The human sees the result in the handoff — not a prompt asking permission to run it.

The cultural shift: agents that ship work without adversarial review look reckless once one that does it exists. The handoff message IS the proof-of-thinking artifact.

**All outcomes are advisory.** dvad is a checkpoint, not a gate. Every outcome — including `critical_found` — is information for the agent to act on, not an instruction to stop. The agent decides whether to address findings, defer them, or proceed. dvad never blocks shipping; it makes shipping without thinking visible.

---

## Capabilities

### 1. MCP Server

An MCP server process that exposes adversarial review as callable tools. Transport: stdio (standard for local MCP servers). The server implements its own lightweight provider abstraction and lite-mode orchestration.

**Tools exposed:**

#### `dvad_review`

The primary tool. Submits an artifact for adversarial review and returns structured findings.

Parameters:

- `artifact` (string, required) — The content to review: a plan, a diff, a spec, code, or any text artifact.
- `artifact_type` (enum: `plan` | `diff` | `spec` | `code` | `test` | `prose`, required) — Determines the review rubric applied.
- `mode` (enum: `lite`, default: `lite`) — Review depth. v1 ships lite mode only. Reserved for future expansion.
- `context` (object, optional) — Additional context the reviewer models receive:
  - `project_name` (string) — Project identifier for tracking.
  - `repo_root` (string) — Path to repository root for file resolution.
  - `reference_files` (string[]) — Paths to key reference files. If omitted, dvad infers from imports/references in the artifact.
  - `instructions` (string) — Additional review instructions or focus areas.
- `parent_review_id` (string, optional) — Links this review to a prior review of the same artifact. Enables the handoff to show iteration progress (e.g., "round 2: 3 findings from round 1 resolved, 1 new finding").
- `budget_limit` (float, optional) — Maximum USD to spend on this review. Overrides session/global defaults. Review aborts if projected cost exceeds this.

Returns (JSON):

```json
{
  "review_id": "a1b2c3d4",
  "parent_review_id": null,
  "artifact_type": "plan",
  "mode": "lite",
  "outcome": "caution",
  "models_used": [
    {"name": "claude-sonnet-4-6", "provider": "anthropic"},
    {"name": "gpt-5", "provider": "openai"},
    {"name": "gemini-2.5-pro", "provider": "google"}
  ],
  "duration_seconds": 22,
  "cost_usd": 0.27,
  "findings": [
    {
      "severity": "critical",
      "consensus": 3,
      "category": "correctness",
      "category_detail": null,
      "issue": "In-memory rate limiter bypassed by multi-pod deployment",
      "detail": "All three reviewers independently identified that...",
      "models_reporting": ["claude-sonnet-4-6", "gpt-5", "gemini-2.5-pro"]
    }
  ],
  "summary": {
    "total": 7,
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 1
  },
  "reviewer_errors": [],
  "token_usage": [
    {"model_id": "claude-sonnet-4-6", "provider": "anthropic", "role": "reviewer", "input_tokens": 7200, "output_tokens": 1400, "cost_usd": 0.023},
    {"model_id": "gpt-5", "provider": "openai", "role": "reviewer", "input_tokens": 7100, "output_tokens": 1300, "cost_usd": 0.019},
    {"model_id": "claude-haiku-4-5-20251001", "provider": "anthropic", "role": "dedup", "input_tokens": 1200, "output_tokens": 400, "cost_usd": 0.003}
  ],
  "tokens_total": 18600,
  "report_markdown": "# dvad Lite Review\n\n## Summary\n..."
}
```

Key design decisions:

- `outcome` is a top-level classification derived from findings: `clean` (no high/critical), `caution` (high findings present), `critical_found` (critical findings present — advisory, not a stop signal), `degraded` (review completed but with reduced model coverage — see Partial Failure Handling). All outcomes are advisory; the agent decides how to proceed. This gives the agent a single-field branch point without parsing the findings array.
- `report_markdown` is embedded in the JSON response, not written to disk. The calling agent decides what to do with it (display inline, attach to PR, save to file).
- `findings` are severity-tagged AND consensus-counted. An agent can filter on `severity >= high AND consensus >= 2` to focus on high-signal issues.
- `review_id` enables follow-up. `parent_review_id` enables iteration tracking across re-reviews of the same artifact.
- `reviewer_errors` lists any models that failed during the review (see Partial Failure Handling).
- `token_usage` is a per-model breakdown of actual token consumption (input/output) and cost. `cost_usd` is `null` when pricing metadata is unavailable for a non-zero call, and `0.0` for zero-token failure paths (timeout, connection error). `role` is sourced from the model's config role ("reviewer" or "dedup"). Present on both `ok` and `failed_review` responses — the human needs the receipt even when the review fails.
- `tokens_total` is the sum of all input + output tokens across all models. Derived from `token_usage`, not stored independently. Agents include this in the handoff summary line when non-zero.
- `category` is a **closed enum** — not free-form. Defined values: `correctness`, `security`, `performance`, `reliability`, `testing`, `maintainability`, `compatibility`, `documentation`, `other`. When `category` is `other`, `category_detail` contains a free-text description. Reviewer model outputs are normalized into this taxonomy during dedup. This enables reliable agent filtering and aggregation without category drift (e.g., `"security"` vs `"vulnerability"` vs `"Security Issues"` collapsing into one consistent value).

#### `dvad_estimate`

Dry-run cost and time estimate before committing to a review.

Parameters: Same as `dvad_review`.

Returns:

```json
{
  "estimated_cost_usd": 0.25,
  "estimated_duration_seconds": 20,
  "total_estimated_tokens": 11940,
  "total_estimated_tokens_in": 2440,
  "total_estimated_tokens_out": 9500,
  "total_estimated_tokens_note": "Approximation: token estimates are based on artifact size only. Actual dvad_review input includes system prompts, rubrics, and reference files, so real token consumption is typically higher.",
  "models_available": [
    {"name": "claude-sonnet-4-6", "provider": "anthropic"},
    {"name": "gpt-5", "provider": "openai"}
  ],
  "minimum_met": true,
  "message": null
}
```

- `total_estimated_tokens` is the sum of estimated input and output tokens across all reviewer and dedup models. Based on artifact size only — actual review consumption is typically higher due to system prompts, rubrics, and reference files.
- If fewer than 2 models are available from detected API keys, `minimum_met` is `false` and `message` explains what's missing. This lets the agent decide whether to proceed (single-model review has limited value) or skip with a note to the human.

#### `dvad_config`

Returns current dvad configuration state. Useful for agents to understand what's available without trial-and-error.

Returns:

```json
{
  "config_source": "auto-detected",
  "models_available": [...],
  "providers_detected": ["anthropic", "openai"],
  "budget_defaults": {
    "per_review": 2.00,
    "daily": 50.00
  },
  "lite_mode_default_models": [...]
}
```

### 2. Claude Code Skill (`/dvad`)

A skill definition (`.md` file with YAML frontmatter) that integrates into Claude Code's skill system. This teaches the agent:

- **When** to invoke adversarial review (post-plan, post-implementation, pre-handoff)
- **How** to call the MCP tools
- **How** to process findings (address critical/high, defer low, note deferred items)
- **How** to format the handoff message with the adversarial trail

The skill is invocable manually (`/dvad`) but its primary value is as behavioral guidance that agents internalize. When installed, the agent's default behavior shifts: it treats adversarial review as a standard checkpoint, not an optional add-on.

**Skill trigger conditions** (agent auto-invokes when):

- An implementation plan has been drafted and is about to be executed
- A non-trivial implementation is complete (>50 lines changed, schema changes, new dependencies, security-adjacent code)
- The agent is about to declare "done" on a task that involved architectural decisions

**Skill does NOT auto-invoke when:**

- Single-file typo fixes, formatting changes, documentation-only edits
- The task is explicitly marked as exploratory/research
- Budget is exhausted

**Multi-agent delegation rule:**

If you are the top-level agent interacting with the human, you own the adversarial checkpoints. Run dvad at plan stage and implementation stage, include findings in your handoff. If you delegated work to a sub-agent, review the sub-agent's output through dvad before presenting it to the human — the sub-agent's internal quality checks don't replace your checkpoint.

### 3. Zero-Config Defaults

dvad v1 agent-native MUST work without a `models.yaml` file. The zero-config path:

1. **Detect API keys** in the environment:
   
   - `ANTHROPIC_API_KEY` → Anthropic provider available
   - `OPENAI_API_KEY` → OpenAI provider available
   - `GOOGLE_API_KEY` or `GEMINI_API_KEY` → Google provider available
   - Additional providers as the provider abstraction expands

2. **Auto-select models** per detected provider. Use a hardcoded default model table:
   
   - Anthropic: `claude-sonnet-4-6` (reviewer), `claude-haiku-4-5-20251001` (dedup)
   - OpenAI: `gpt-5` (reviewer)
   - Google: `gemini-2.5-pro` (reviewer)
   - Defaults update with dvad releases as model landscape shifts.

3. **Auto-assign roles:**
   
   - Reviewers: one model per detected provider (cross-provider diversity preferred)
   - Dedup/normalization: cheapest available model

4. **Minimum viable config:** 1 API key providing access to 2+ distinct models. If only one model is available total, `dvad_review` returns an error explaining that adversarial review requires model diversity, and suggests adding a second provider key.

5. **Override path:** If `models.yaml` exists (at project-local, `$DVAD_HOME`, or XDG path), it takes precedence. Zero-config is the fallback, not the override. Power users keep their existing config; new users never touch it.

6. **First-run behavior:** On first invocation, if no API keys are detected and no `models.yaml` exists, `dvad_review` returns a structured `setup_required` response (not an opaque error):

```json
{
  "status": "setup_required",
  "message": "No LLM providers detected. dvad requires at least 2 models for adversarial review.",
  "setup_steps": [
    "Set ANTHROPIC_API_KEY in your environment (https://console.anthropic.com/)",
    "Set OPENAI_API_KEY in your environment (https://platform.openai.com/)",
    "Restart your MCP client to pick up the new keys"
  ],
  "docs_url": "https://github.com/briankelley/dvad-agent-native#setup"
}
```

This converts installation failures into guided recovery. The agent can relay this to the human as actionable instructions rather than a cryptic tool error.

### 4. Lite Mode

The default for agent-invoked reviews. Optimized for speed and cost over depth.

**Pipeline:**

1. **Pre-scan artifact for secrets** (see Secrets Scanning below)
2. Fan out artifact + rubric to all available reviewer models in parallel
3. Collect findings from each model; handle partial failures gracefully (see Partial Failure Handling)
4. Deduplicate using cheapest available model (or deterministic fuzzy-match if cost is a concern)
5. Severity-tag and consensus-count each finding
6. Derive top-level `outcome` classification
7. Return structured JSON + embedded markdown

**What's skipped vs. full mode:**

- No author response (the calling agent IS the author — it processes findings directly)
- No rebuttal round
- No governance resolution
- No revision generation

**Target performance:**

- <30 seconds for a plan/diff under 5,000 tokens with 3 models
- <$0.50 per invocation at current API pricing (3 models, moderate input)

**Rubric per artifact type:**

- `plan`: Correctness, feasibility, missing considerations, unstated assumptions, blast radius
- `diff`: Bugs, race conditions, security issues, test coverage gaps, backward compatibility
- `spec`: Completeness, internal consistency, ambiguity, missing edge cases
- `code`: Same as diff but without the before/after framing
- `test`: Vacuous assertions, insufficient branch/negative coverage, over-mocking, whether tests would actually catch the bugs they claim to prevent, false-completeness patterns
- `prose`: Logical coherence, unsupported claims, missing counterarguments (for emails, docs, decisions)

### 5. Full Mode (Future Bridge)

v1 ships lite mode only. Full adversarial review — with author response, rebuttal rounds, and governance resolution — is available today via the dvad core CLI (`dvad review`). dvad-agent-native does not reimplement or wrap that pipeline.

A future bridge is possible: dvad-agent-native could shell out to dvad core for full-mode reviews, or dvad core could expose its own MCP interface. That's a design decision for after v1 ships and lite mode proves its value. For v1, if a user wants full-mode depth, they run `dvad review` directly.

Full mode is appropriate when:

- The artifact is high-stakes (production schema migration, security-critical code, public API changes)
- Lite mode findings suggest fundamental issues that warrant deeper adversarial examination
- The human explicitly wants the full adversarial cycle (author response, rebuttals, governance)

### 6. Dual Output

Every review produces two representations of the same findings:

**Structured JSON** (for agents): Machine-parseable findings with severity, consensus, category. Enables programmatic filtering (`findings.filter(f => f.severity >= "high" && f.consensus >= 2)`). Embedded in the MCP tool response.

**Markdown report** (for humans): Readable narrative. Embedded in the JSON response as `report_markdown`. The calling agent includes this in its handoff message, attaches it to a PR, or saves it — dvad doesn't decide.

Both formats are generated from the same underlying findings. No information is in one but not the other.

### 7. Consent and Cost Model

dvad does not manage consent itself. It provides the information; the calling harness (Claude Code, Cursor, etc.) handles the UX.

**What dvad provides:**

- `dvad_estimate` tool for pre-flight cost/time estimates
- `budget_limit` parameter on `dvad_review` to hard-cap spend per invocation
- Actual cost reported in every response (`cost_usd` field)
- Budget state tracked per session (cumulative spend available via `dvad_config`)

**Recommended harness behavior** (documented in the Claude Code skill, not enforced by dvad):

- First invocation in a session: agent discloses intent and estimated cost before calling `dvad_review`
- Subsequent invocations: silent, within budget, cost shown in handoff
- Budget breach: agent reports that review was skipped due to budget and notes it in handoff
- Configurable budget defaults in dvad config (per-review cap, daily cap)

**Budget defaults (zero-config):**

- Per-review: $2.00 (generous for lite mode, adequate for modest full-mode reviews)
- Daily: $50.00
- Both overridable via config file or environment variables (`DVAD_BUDGET_PER_REVIEW`, `DVAD_BUDGET_DAILY`)

### 8. Stateless Invocation

Each `dvad_review` call is a pure function: artifact in, findings out. No lock directories, no on-disk state required for the review itself.

**What IS persisted (optional, for audit trail):**

- Review results saved to `~/.local/share/devils-advocate/reviews/{review_id}/` (same location as existing dvad)
- Budget state tracked in-memory per server process lifetime (resets on restart)
- These are write-only side effects — the review does not depend on prior state

**What is NOT required:**

- No `.dvad/` lock directory for MCP-invoked reviews
- No project-local state
- No prior review history to function

### 9. Secrets Scanning

*Added in spec.v2 — flagged at 2/2 consensus by both review pairs.*

Before sending any artifact content to external LLM providers, dvad performs a local pre-scan for secrets and sensitive data. This is a **hard gate** in the lite-mode pipeline — it runs before any API call is made.

**What's scanned:**

- Common secret patterns: API keys (AWS, GCP, Stripe, etc.), private keys (`BEGIN RSA/EC/OPENSSH PRIVATE KEY`), connection strings with embedded credentials, `.env`-style `KEY=value` patterns with high-entropy values
- File path indicators: references to `.env`, `credentials.json`, `secrets.yaml`, key vault paths

**Behavior on detection:**

- **Default: abort with explanation.** The review does not proceed. The response includes which patterns were detected and their approximate locations in the artifact. The agent relays this to the human.
- **Configurable: redact and proceed.** If `secrets_handling: "redact"` is set in config, dvad replaces detected secrets with stable placeholders (`[REDACTED_1]`, `[REDACTED_2]`) before sending to providers. The mapping is held in-memory only (never persisted) and findings reference the placeholders. The human sees the original artifact alongside the redacted findings.

**What this is NOT:**

- Not a security audit tool. It's a basic regex/pattern pre-scan to prevent obvious secret leakage. It does not guarantee detection of all secrets.
- Not configurable per-provider (e.g., "trust Anthropic but redact for OpenAI"). v1 treats all external providers equally.

### 10. Partial Failure Handling

*Added in spec.v2 — flagged by GPT-5.4 + MiniMax review.*

When reviewer models are called in parallel, one or more may fail (timeout, rate limit, API error). dvad handles this deterministically:

- **≥2 reviewers succeed:** Review proceeds with successful outputs. Failed models are listed in `reviewer_errors` with the failure reason. `outcome` is set to `degraded` if a model that would have provided cross-provider diversity was the one that failed. The handoff notes reduced coverage.
- **<2 reviewers succeed:** Review aborts. Response includes `reviewer_errors` explaining what failed and a `message` suggesting retry or checking API key validity.
- **Dedup model fails:** If the designated dedup model fails, dvad falls back to the cheapest available reviewer model for dedup. If no models are available for dedup, findings are returned un-deduplicated with a `dedup_skipped: true` flag and a note in the markdown report.

### 11. Progress Signaling

*Added in spec.v2 — flagged by both review pairs.*

During a lite-mode review (~20-30 seconds), the MCP server emits progress notifications so the calling harness can avoid dead-air silence:

- `"Starting review: 3 models, estimated 20s"`
- `"Reviewer 1/3 complete (claude-sonnet-4-6)"`
- `"Reviewer 2/3 complete (gpt-5)"`
- `"Reviewer 3/3 complete (gemini-2.5-pro)"`
- `"Deduplicating findings..."`
- `"Review complete"`

Implementation uses MCP's standard progress notification mechanism if supported by the transport. If not (e.g., minimal stdio clients), progress is silently skipped — the final response is unaffected.

---

## Agent Handoff Format

The Claude Code skill defines a recommended handoff format. This is the visible artifact — the thing the human reads that makes "done without adversarial review" feel reckless by comparison.

```
[task completion summary]

Adversarial review ([N] models, [rounds] round(s), $[cost]):

  [Round label — e.g., "Plan stage" or "Implementation"]
    [severity/consensus] [issue summary]    → [resolution: fixed / deferred / out of scope]

  [Round label]
    [severity/consensus] [issue summary]    → [resolution]

  Final pass: [clean / N remaining items]

Open questions for you:
  1. [Deferred items requiring human judgment]
```

The format is terse, scannable, and shows the adversarial trail without burying the task completion. The human sees: what was built, what was challenged, what was fixed, what's left for them.

---

## Relationship to dvad Core

dvad-agent-native is a **separate repository and product**. It does not import, depend on, or modify dvad core.

### What may be ported (copied, not imported):

- **Provider call patterns** — how to call Anthropic, OpenAI, Google APIs via httpx with retries and token tracking. The approach is well-proven in dvad core; the implementation should be rewritten to be minimal and focused on the needs of lite-mode review (no SDK lock-in, async parallel fan-out, cost-per-call tracking).
- **Dedup prompt patterns** — the rubric/instructions used to deduplicate findings across models. This is prompt engineering, not code architecture.
- **Cost-per-token tables** — pricing data for budget estimation.

### What is NOT ported:

- The full review pipeline (governance, author response, rebuttals, revision)
- The Flask GUI
- The Click CLI
- Storage manager, lock directories, systemd service management
- The 1,773-test suite and its supporting infrastructure

### Why standalone:

1. **Lite mode is ~300-500 lines of focused code.** The MCP server wrapper adds another ~100-200. The entire product is smaller than dvad core's test suite. Building "on top" would drag 90% of dvad's complexity as dead weight.
2. **OSS adoption favors small, readable repos.** A developer evaluating an MCP server wants to read it in 10 minutes and install it in one command. A dependency on a 1,773-test CLI+GUI application kills that.
3. **Independent evolution.** dvad core serves human-driven deep adversarial review. dvad-agent-native serves fast agent-invoked checkpoints. Different users, different performance profiles, different release cadences. Coupling them slows both down.
4. **Full mode is a future bridge, not a v1 dependency.** If full-mode reviews are needed, the user installs dvad core separately. A bridge between the two products can be designed later, after v1 proves the lite-mode concept.

---

## Non-Goals (Explicit v2 / Out of Scope)

These are things dvad v1 agent-native deliberately does NOT do:

- **IDE-native integration.** No gutter annotations, inline diagnostics, VS Code extension, JetBrains plugin, or Cursor-specific features. v2, with a collaborator who lives in the IDE.
- **CI/CD integration.** No GitHub Actions, no PR-commenting bot, no merge-gate webhook. The MCP server is the primitive; CI integration is a wrapper someone (or v2) builds on top.
- **dvad-as-hosted-service.** No SaaS, no hosted API, no user accounts, no billing. v1 runs locally using the user's own API keys.
- **Changes to dvad core.** dvad-agent-native is a separate product. dvad core's CLI, GUI, and pipeline are unmodified and unaffected.
- **Automatic reference file discovery.** v1 accepts optional `reference_files` in context but does NOT crawl the repo to find relevant files. If omitted, reviewers work with the artifact alone. Intelligent context inference is a meaningful feature that deserves its own design cycle.
- **Model fine-tuning or custom rubrics via MCP.** The built-in rubrics per artifact type are the v1 offering. Custom rubrics are a power-user feature for later.
- **Multi-turn review sessions.** Each `dvad_review` call is standalone. There's no "continue reviewing" or "review in light of my fixes." The agent calls dvad again with the revised artifact — that's a new review, not a continuation.

---

## Success Criteria

dvad v1 agent-native is successful when:

1. **A Claude Code user can install the MCP server and skill with two commands** (or fewer) and have adversarial review available in their next session without editing any config files, given at least two provider API keys in their environment.

2. **An agent can invoke `dvad_review` in lite mode and receive structured findings in under 30 seconds** for a typical plan or diff (<5K tokens).

3. **The agent's handoff message, with adversarial trail included, is visibly better than a handoff without it** — to the point where a developer who's seen it once would not accept a bare "done, tests pass" handoff again.

4. **The codebase is small enough that a contributor can read it end-to-end in under 30 minutes.** No dead weight, no inherited complexity from dvad core.

5. **A dvad review of THIS SPEC, run through the dvad core CLI against SOTA models, produces findings that improve the spec.** (Meta-success: dvad validates its own successor's product direction.)

---

## Open Questions (For adversarial review to attack)

1. **Lite mode dedup: model-based or deterministic?** Model-based dedup is more accurate but adds cost and latency. Deterministic fuzzy-match (embedding similarity or keyword overlap) is faster but less precise. What's the right default for a <30s target?

2. **Reference file inference: how much is too much?** The spec says "out of scope" for v1, but the agent already has repo context. Should the skill definition teach the agent to pass key files, or should dvad accept a repo root and figure it out? The current CLI's `--input` pattern is human-centric but effective.

3. **Provider-internal diversity: is Claude-Opus vs Claude-Sonnet "adversarial enough"?** When only one API key is available, dvad can still pit models from the same provider against each other. Is this meaningfully adversarial, or is it theater? Should dvad warn users when diversity is low?

---

## Prior Review Dispositions

The following suggestions were raised during adversarial review of spec.v1 and have been evaluated. They are documented here so subsequent reviewers do not re-raise them.

### Incorporated into spec.v2

- **Secrets scanning / redaction before external calls** — 2/2 consensus, both review pairs. Added as Capability §9.
- **Partial failure handling for reviewer models** — Added as Capability §10.
- **Top-level outcome classification** — Added to `dvad_review` response.
- **`parent_review_id` for review lineage** — Added to `dvad_review` parameters and response.
- **Progress signaling during review** — Added as Capability §11.
- **First-run `setup_required` structured response** — Added to Zero-Config Defaults §6.
- **`test` as artifact type with dedicated rubric** — Added to artifact_type enum and rubrics.

### Incorporated into spec.v3

- **Rename `blocked` → `critical_found`** — 2/2 consensus (Opus+GPT). The word "blocked" implies a gate; dvad is a checkpoint. All outcomes are advisory. Renamed and documented.
- **Closed category taxonomy** — Both round 2 reviews. `finding.category` is now a closed enum with `category_detail` for outliers. Prevents category drift in agent filtering.
- **Multi-agent delegation guidance** — Resolves Open Question #4. The top-level agent owns the checkpoint; sub-agent internal checks don't replace it. Added to skill definition.

### Deferred to v2 or later

- **Structured remediation per finding** (`suggested_action`, `suggested_test`, `verification_hint`) — Changes the product surface from "find problems" to "generate fixes." Valuable, but a different capability that deserves its own design. v2.
- **Local review analytics / telemetry dashboard** (`dvad_stats`) — Valuable for proving ROI but not a launch feature. Requires persistence infrastructure that contradicts v1's stateless-first philosophy.
- **Review replay / reasoning transparency** (`dvad_explain`) — Trust-building feature; prove findings are useful before investing in explaining them.
- **Focus tags beyond artifact type** (security, performance, migration_risk) — Built-in rubrics need to prove themselves before adding composition.
- **Stage-aware checkpoint labeling** — Useful for multi-checkpoint trails but the handoff format already implies stage via round labels.
- **HTTP/SSE transport** — v1 ships stdio only. HTTP opens shared-service and remote-dev scenarios but adds deployment complexity.
- **PR-ready / ADR-ready report variants** — Alternate markdown renderings are useful but the single `report_markdown` format needs to prove itself first.
- **Deferred-finding handoff to issue trackers** — GitHub/Linear integration is a wrapper on top of the MCP primitive, not a v1 feature.
- **Structured delta for `parent_review_id`** — v1 ships `parent_review_id` as metadata linkage. Structured `new/resolved/persisting` delta requires reading prior state from storage, tensions with stateless invocation. Add once persistence patterns settle.
- **Batch / multi-artifact review** — Cross-artifact consistency checking in one call. Adds real pipeline complexity. v2.
- **Finding location hints** (`file_path`, `approx_lines`) — Useful for IDE integration but no v1 consumer.
- **Additional artifact types** (`migration`, `adr`) — Dedicated rubrics for migrations and architecture decisions. Wait until core types prove the pattern.
- **Dissent preservation** — Keep outlier findings dedup would drop. Current consensus model should prove itself first.
- **Agreement metric** — Analytical meta-signal about reviewer convergence. Not v1.

### Rejected (not planned)

- **Community rubric registry / URI packs** — Ecosystem thinking before there's an ecosystem. Build the ecosystem first.
- **Adversarial persona assignment** (`persona_mix`) — Creative concept, unproven value. The diversity comes from cross-provider model differences, not assigned roles. If the models already disagree meaningfully (which is dvad's thesis), personas add prompt complexity without clear gain.
- **Temporal consensus decay / model freshness weighting** — Over-engineers the consensus mechanism. Consensus count is simple and interpretable; freshness-weighted scoring adds hidden complexity that's hard to debug.
- **Author provenance / blind-spot calibration** — Interesting research direction, not a product feature. Requires persistent profiling infrastructure.
- **Multi-modal artifact review** (images, diagrams via URI + mime_type) — v1 is text-only. Future-proofing the schema for this adds nothing until multimodal review rubrics exist.
- **SARIF / LSP diagnostic export** — v2 IDE integration territory. No value without an IDE consumer.
- **Docker packaging** — Premature. pip/pipx install is the right v1 distribution. Docker adds maintenance burden for a tool that has no server infrastructure.
- **Hot-reload config** — Over-engineered for a tool that reads config once at startup. Restart the server.
- **Team dashboards / shareable gallery** (`dvad_share`) — Social/adoption features for after the product proves useful to individuals.
- **Emergency override / force_approve** — Agents already have the option to skip dvad and note it in handoff. A formal bypass mechanism implies dvad is a gate, which it isn't — it's a checkpoint. The agent decides what to do with findings.
- **Machine-readable fix-it suggestions / patches** (`suggested_fix`) — Same reasoning as structured remediation. Turns dvad from reviewer into fixer. Different product surface.
- **Repo-level policy triggers** (`.dvad/policy.yaml`) — Configuration-as-code for teams is a good idea that requires the product to exist and have users first.
- **Epistemic status granularity** (`certain`, `likely`, `speculative`) — Over-engineers severity. Four levels (critical/high/medium/low) plus consensus count already captures confidence.
- **Tiered model selection presets** (`quick`/`standard`/`thorough`) — v1 has one mode (lite). Tiers are premature until there's a second mode to tier against.
- **Interactive team calibration** (`dvad_calibrate`) — Enterprise onboarding feature. Requires a team, a workflow, and an existing installation.
- **Context window smart truncation with priority markers** — Interesting for large artifacts but adds complexity to a pipeline that should be simple. If the artifact is too large, the agent should chunk it before calling dvad.
- **Asynchronous background review jobs** — v1 lite mode targets <30s. Background jobs solve a problem that doesn't exist at this latency.
- **Capability negotiation flags in `dvad_config`** — Premature abstraction. v1 has one mode with fixed capabilities. Negotiate when there's something to negotiate.
- **Plain-English summary mode for non-experts** — Audience targeting is a v2 concern. v1's audience is developers and their agents.
- **`dvad_demo` fixture reviews for zero-keys evaluation** — Nice onboarding touch but requires maintaining canned responses. The first-run `setup_required` response is the v1 answer.
- **`dvad_doctor` / `dvad_validate`** — Diagnostic tooling for a product with three configuration inputs (API keys) is over-engineered. `dvad_config` already reports what's available. If a key is invalid, the first review will fail with a clear error.
- **Adaptive reviewer selection based on artifact domain** — Model selection via heuristics adds hidden complexity. Let the user/config choose models; don't guess.
- **Per-model contributor tracking** (`model_perspectives`) — Dedup exists to collapse perspectives into findings. Preserving raw perspectives adds response bulk without clear consumer.
- **Structured open questions with resolution options + effort** — Over-structures the handoff. The agent already presents deferred items with context; adding effort estimates is speculative.
- **Agent invocation policy profiles** (`conservative`/`standard`/`paranoid`) — The skill definition already describes trigger conditions. Named profiles add a configuration layer on top of something that should be implicit.
- **Proof-of-thinking badges / commit trailers** — Cultural adoption artifact. Good idea for a blog post or README example, not a product feature.
- **Screen-reader-friendly report conventions** — Valid accessibility concern but `report_markdown` is standard markdown. Accessibility of the consuming UI (terminal, IDE, web) is the consumer's responsibility, not dvad's.
- **Prompt injection pre-scan** — Multi-model adversarial design is itself the defense. Regex detection is trivially bypassed and false-positives on legitimate content (test files, documentation). Not a security scanner.
- **Dedup merge confidence** (`merge_confidence`) — Over-instruments dedup. Fix bad merges with better dedup prompts, not confidence scores.
- **Hallucination guard / meta-check** — Consensus already mitigates: one model hallucinating gets low consensus.
- **Review-of-the-review auto-arbitration** — The disagreement IS the signal; arbitrating it away defeats the purpose.
- **Namespaced env vars** (`DVAD_ANTHROPIC_KEY`) — Fragments the ecosystem. Standard provider env vars are the convention.
- **Review caching by content hash** — Reviews are cheap (<$0.50). Cache invalidation is harder than re-running.
- **Reviewer model rotation across reviews** — Budget rarely limits reviewer count in lite mode. Config decision, not algorithm.
- **`dvad_should_review` heuristic tool** — Skill trigger conditions already describe when to skip.
- **CI-discoverable output files** — CI integration is explicitly v2.
- **Ledger format compatibility with dvad core** — Separate products, separate schemas. Compatibility coupling defeats standalone design.
- **Non-English artifact support** (`language` param) — Reviewer models handle multilingual input natively.
- **Artifact type auto-detection** — Trusting heuristics over explicit caller labels adds hidden complexity. The agent knows what it's submitting.
- **Debug mode exposing reviewer prompts** — Prompts are implementation detail, not product surface.
- **Cost-tiered model selection** (`cost_tier`) — One mode, one tier. Premature.
- **Provider health canary before fan-out** — Partial failure handling covers this. A canary adds latency to every call to save latency on rare failures.
- **Configurable severity thresholds for outcome** — Aligns with org risk appetite but requires teams using the product first. v3/ecosystem.
- **`.dvad-ignore` content exclusion** — Enterprise adoption feature beyond basic secrets scanning. v3/ecosystem.

---

## dvad Review Command

To run this spec through dvad for adversarial review:

```bash
/media/kelleyb/DATA2/code/tools/devils-advocate/.venv/bin/dvad review \
  --mode spec --project dvad-v1-agent-native \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/spec.v3.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/providers.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/config.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/dedup.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/output.py
```
