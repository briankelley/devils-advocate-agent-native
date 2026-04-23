# dvad v1 Agent-Native Spec

**Status:** Draft for adversarial review
**Date:** 2026-04-22
**Author:** Brian Kelley + Claude (strategic conversation, not generated slop)

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

---

## Capabilities

### 1. MCP Server

An MCP server process that exposes adversarial review as callable tools. Transport: stdio (standard for local MCP servers). The server implements its own lightweight provider abstraction and lite-mode orchestration.

**Tools exposed:**

#### `dvad_review`

The primary tool. Submits an artifact for adversarial review and returns structured findings.

Parameters:

- `artifact` (string, required) — The content to review: a plan, a diff, a spec, code, or any text artifact.
- `artifact_type` (enum: `plan` | `diff` | `spec` | `code` | `prose`, required) — Determines the review rubric applied.
- `mode` (enum: `lite`, default: `lite`) — Review depth. v1 ships lite mode only. Reserved for future expansion.
- `context` (object, optional) — Additional context the reviewer models receive:
  - `project_name` (string) — Project identifier for tracking.
  - `repo_root` (string) — Path to repository root for file resolution.
  - `reference_files` (string[]) — Paths to key reference files. If omitted, dvad infers from imports/references in the artifact.
  - `instructions` (string) — Additional review instructions or focus areas.
- `budget_limit` (float, optional) — Maximum USD to spend on this review. Overrides session/global defaults. Review aborts if projected cost exceeds this.

Returns (JSON):

```json
{
  "review_id": "a1b2c3d4",
  "artifact_type": "plan",
  "mode": "lite",
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
  "report_markdown": "# dvad Lite Review\n\n## Summary\n..."
}
```

Key design decisions:

- `report_markdown` is embedded in the JSON response, not written to disk. The calling agent decides what to do with it (display inline, attach to PR, save to file).
- `findings` are severity-tagged AND consensus-counted. An agent can filter on `severity >= high AND consensus >= 2` to focus on high-signal issues.
- `review_id` enables follow-up (re-review after fixes, audit trail).

#### `dvad_estimate`

Dry-run cost and time estimate before committing to a review.

Parameters: Same as `dvad_review`.

Returns:

```json
{
  "estimated_cost_usd": 0.25,
  "estimated_duration_seconds": 20,
  "models_available": [
    {"name": "claude-sonnet-4-6", "provider": "anthropic"},
    {"name": "gpt-5", "provider": "openai"}
  ],
  "minimum_met": true,
  "message": null
}
```

If fewer than 2 models are available from detected API keys, `minimum_met` is `false` and `message` explains what's missing. This lets the agent decide whether to proceed (single-model review has limited value) or skip with a note to the human.

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

### 4. Lite Mode

The default for agent-invoked reviews. Optimized for speed and cost over depth.

**Pipeline (simplified from existing dvad):**

1. Fan out artifact + rubric to all available reviewer models in parallel
2. Collect findings from each model
3. Deduplicate using cheapest available model (or deterministic fuzzy-match if cost is a concern)
4. Severity-tag and consensus-count each finding
5. Return structured JSON + embedded markdown

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

4. **How should the skill handle agent-to-agent delegation?** If a sub-agent is doing implementation work, should the sub-agent run dvad, or should the parent agent run dvad on the sub-agent's output? Who owns the checkpoint?

---

## dvad Review Command

To run this spec through dvad for adversarial review:

```bash
/media/kelleyb/DATA2/code/tools/devils-advocate/.venv/bin/dvad review \
  --mode spec --project dvad-v1-agent-native \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/spec.v1.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/providers.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/config.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/dedup.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/output.py
```
