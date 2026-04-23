# dvad-agent-native v1 — Implementation Plan

**Status:** Draft — ready for adversarial review
**Date:** 2026-04-22
**Spec reference:** `docs/spec.v3.md` (Final draft, reviewed by 6 models across 4 pairings)

---

## dvad Review Command

```bash
/media/kelleyb/DATA2/code/tools/devils-advocate/.venv/bin/dvad review \
  --mode plan --project dvad-v1-agent-native \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/plan.v1.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/spec.v3.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/providers.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/config.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/dedup.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/output.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/prompts.py
```

---

## 1. Guiding Constraints (from spec and conversation)

These are the non-negotiables the build measures itself against. If any decision in this plan breaks one of these, the decision is wrong.

1. **10-minute read.** A contributor cloning the repo must be able to read it end-to-end in under 30 minutes; a casual evaluator must be able to understand the shape in 10. Target total: ~700–900 LoC of production Python, excluding tests and generated artifacts.
2. **Standalone.** No import dependency on dvad core. Port patterns; do not wrap.
3. **Lite mode only.** No governance, no author response, no revision, no rebuttals. Full-mode depth lives in dvad core; a bridge is a future question.
4. **Stateless invocation.** Each `dvad_review` call is a pure function. Persistence is a write-only side effect for audit, never a read dependency.
5. **Zero-config.** Works with just API keys in env. `models.yaml` is an override path, never a prerequisite.
6. **Advisory, not gate.** Every outcome — including `critical_found` — is information, not a stop signal. The word choice in error messages, outcomes, and logs reflects this.
7. **Secrets never leave without consent.** Pre-scan is a hard gate before any external API call. No exceptions for performance.

---

## 2. Architecture at a Glance

```
devils-advocate-agent-native/
├── pyproject.toml                  (pipx-installable, entry points for CLI + MCP server)
├── README.md                       (install line, one demo, link to spec)
├── LICENSE                         (MIT)
├── docs/
│   ├── spec.v3.md                  (frozen product definition)
│   ├── plan.v1.md                  (this file)
│   ├── roadmap.md                  (v2/v3/rejected)
│   └── conversation.01.md          (strategic origin, for future context)
├── src/dvad_agent/
│   ├── __init__.py
│   ├── __main__.py                 (python -m dvad_agent → CLI; for local debugging only)
│   ├── providers.py                (~200 LoC — httpx calls to Anthropic/OpenAI/Google)
│   ├── config.py                   (~150 LoC — key detection, model defaults, budgets)
│   ├── secrets.py                  (~100 LoC — regex/pattern pre-scan, redact mode)
│   ├── review.py                   (~200 LoC — lite-mode orchestrator, fan-out, outcome)
│   ├── dedup.py                    (~120 LoC — model-based dedup with deterministic fallback)
│   ├── output.py                   (~150 LoC — markdown renderer + JSON shaping)
│   ├── prompts.py                  (~100 LoC — rubric per artifact_type, dedup prompt)
│   ├── cost.py                     (~60 LoC — token estimate, pricing table, budget check)
│   ├── types.py                    (~80 LoC — dataclasses: Finding, ReviewResult, ModelConfig)
│   ├── server.py                   (~180 LoC — MCP stdio server, 3 tools, progress signals)
│   └── cli.py                      (~80 LoC — thin wrapper for local testing)
├── skill/
│   └── dvad.md                     (Claude Code skill definition with YAML frontmatter)
└── tests/
    ├── test_secrets.py             (regex catches the obvious, doesn't trip on lookalikes)
    ├── test_config.py              (key detection, override precedence, budget defaults)
    ├── test_review.py              (partial failure paths, outcome derivation, minimum-met)
    ├── test_dedup.py               (deterministic fallback shape; model path mocked)
    ├── test_prompts.py             (rubric per artifact_type renders)
    └── test_server.py              (MCP tool schemas, error → setup_required, budget abort)
```

**Why Python:** dvad core is Python; provider patterns port cleanly; MCP has a first-party Python SDK (`mcp` package); pipx is the cleanest single-command install path for a local server. No compelling reason to change languages.

**Why httpx and not provider SDKs:** dvad core's providers.py rationale ports directly — no SDK version lock-in, tiny dependency footprint, async-native. Rewrite, don't import.

**Why a separate CLI:** strictly for developer sanity during the build. The product surface is MCP. The CLI lets you invoke `dvad_agent review --artifact-type plan --file some.md` without standing up an MCP client. It exists for smoke testing and debugging; the README barely mentions it.

---

## 3. Work Breakdown

Phases are ordered so each one produces a testable deliverable. Do not start phase N+1 until phase N runs clean.

### Phase 0 — Scaffolding (half day)

**Deliverable:** Empty-but-installable package. `pipx install -e .` works; `dvad-agent --help` prints; `dvad-agent-mcp` starts and exits cleanly on EOF.

- `pyproject.toml` with `project.scripts` entries for both CLI (`dvad-agent`) and MCP server (`dvad-agent-mcp`)
- Dependencies: `httpx`, `mcp`, `pyyaml`, `click` (or stdlib argparse — choose before writing, don't switch later)
- Package skeleton: every module listed above exists with a docstring and maybe a `pass`
- `README.md` stub with the install line and a "coming soon" demo placeholder
- `LICENSE` (MIT)
- `.gitignore`, `.editorconfig`, pre-commit config with `ruff` + `black`

**Success check:** `pipx install -e .` and both entry points resolve.

### Phase 1 — Types and Config (half day)

**Deliverable:** You can run `dvad-agent config` and see a JSON blob describing what providers/models are available from the current environment.

- `types.py`: `ModelConfig`, `ProviderKey`, `Finding`, `Severity` enum, `Category` enum (closed, 9 values + `other`), `Outcome` enum (`clean` | `caution` | `critical_found` | `degraded`), `ReviewResult`, `ReviewerError`
- `config.py`:
  - Env-key detection: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` / `GEMINI_API_KEY`
  - Hardcoded default model table keyed by provider (values come straight from spec §Zero-Config Defaults; cited to `spec.v3.md` so updates are traceable)
  - Budget defaults: `$2.00/review`, `$50.00/day`; override via `DVAD_BUDGET_PER_REVIEW` / `DVAD_BUDGET_DAILY`
  - `models.yaml` override path resolution (project-local → `$DVAD_HOME` → XDG)
  - `detect_providers()` → list of active providers; `select_models(role="reviewer"|"dedup")` → list of `ModelConfig`
- `cost.py`: token estimator (port dvad core's 4-chars-per-token heuristic, unchanged), `estimate_cost(model, in_tokens, out_tokens)`, per-provider pricing table
- `cli.py` wires up a `config` subcommand that prints `dvad_config`-shaped JSON

**Success check:** With only `ANTHROPIC_API_KEY` set, config reports 1 provider, `minimum_met: false`, and names what's missing. With two keys, `minimum_met: true` and the right models are listed.

### Phase 2 — Provider Layer (1 day)

**Deliverable:** `python -m dvad_agent probe --model claude-sonnet-4-6 --prompt "say hi"` returns a short response and a usage dict.

Port from `devils-advocate/src/devils_advocate/providers.py`, but strip:
- The `thinking` budget logic (lite mode doesn't need reasoning modes; the reviewer models produce findings, they don't need 10k-token internal monologues)
- MiniMax support (the spec doesn't list it as a default provider for v1 — add later if adopted)
- Mode-dependent branching (`spec` / `plan` / `code` / `dedup`)

Keep:
- `call_anthropic`, `call_openai_compatible`, `call_google` as async functions that each return `(text, usage_dict)`
- `call_with_retry(...)` wrapper with exponential backoff + jitter, 529-specific budget
- httpx-only, no SDK dependency

Add:
- Uniform cost attribution: every call returns tokens; the caller converts to USD using `cost.estimate_cost`
- A top-level `call_model(model: ModelConfig, system, user) -> (text, usage, cost)` that dispatches by `model.provider`

**Success check:** The probe command works for each of the three providers independently (given the relevant key).

### Phase 3 — Secrets Pre-Scan (half day)

**Deliverable:** `dvad-agent scan --file path/to/artifact.md` returns a JSON list of suspected secret locations, or `[]`.

- Pattern set: AWS keys (`AKIA[0-9A-Z]{16}`), `BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY`, Stripe live keys, GitHub PATs, Slack tokens, generic `KEY=high-entropy-value` heuristic, connection strings with embedded passwords
- File-path reference heuristics: mentions of `.env`, `credentials.json`, `secrets.yaml`, key vault paths
- Entropy check for `KEY=VALUE` lines: reject low-entropy values (template placeholders, test fixtures) to keep false-positive rate tolerable
- Two modes: `abort` (default) and `redact`
  - `redact` replaces matches with stable placeholders (`[REDACTED_1]`, `[REDACTED_2]`) and returns a mapping held in memory, never persisted
- Hard rule: secrets scan runs before any `call_model` invocation. Enforce via orchestrator, not via trust.

**Success check:** A crafted artifact containing each pattern is either aborted or cleanly redacted. A crafted "false positive" artifact (test file that documents secret patterns) doesn't trip when entropy gate is tuned.

### Phase 4 — Lite-Mode Review Orchestrator (1.5 days)

**Deliverable:** `dvad-agent review --artifact-type plan --file plan.md` returns a `ReviewResult` JSON with findings, outcome, and cost.

- `review.py` implements `async def run_lite_review(artifact, artifact_type, context, budget_limit) -> ReviewResult`
- Pipeline (matches spec §Lite Mode):
  1. Secrets pre-scan → abort or redact
  2. Pre-flight cost estimate; if > `budget_limit`, abort with clear `Outcome`-shaped error (but this is NOT an `Outcome.critical_found` — it's a `ReviewSkipped`-style response, different status)
  3. Build rubric prompt for `artifact_type` (from `prompts.py`)
  4. Fan out reviewer models in parallel via `asyncio.gather(..., return_exceptions=True)`
  5. Collect `ReviewerError` entries for any failure; apply partial-failure rule (≥2 ok → proceed, <2 → abort)
  6. Parse each reviewer's response into `Finding[]` — use a lightweight JSON-mode prompt so parsing is deterministic (no free-form markdown parsing)
  7. Dedup via `dedup.py` (see Phase 5)
  8. Normalize categories into the closed enum; anything off-taxonomy → `other` + `category_detail`
  9. Severity-tag, consensus-count, derive `Outcome`
  10. Render `report_markdown` via `output.py`
  11. Assemble `ReviewResult`; optional persistence to `~/.local/share/devils-advocate/reviews/{review_id}/`

- `prompts.py` contains:
  - Shared preamble establishing the adversarial frame
  - A rubric block per `artifact_type`: `plan` / `diff` / `spec` / `code` / `test` / `prose` (content drawn from spec §Rubric per artifact type — the `test` rubric explicitly names vacuous assertions, over-mocking, false-completeness)
  - JSON output contract the reviewer must follow (keys: `severity`, `category`, `issue`, `detail`)

- `review_id` is a short random hash (8 chars, URL-safe); `parent_review_id` is accepted but only recorded as metadata in v1 (no delta computation — explicitly deferred per spec)

**Success check:** A plan artifact with a known weakness produces at least one finding when run against two real providers. Duration stays under 30s for a 5K-token plan. `outcome` derives correctly from findings (`critical` in any finding → `critical_found`; `high` → `caution`; else `clean`; any reviewer error collapsing a provider → `degraded`).

### Phase 5 — Dedup (half day)

**Deliverable:** Dedup collapses three reviewers' overlapping findings into a single entry with `consensus: 3`.

- Primary path: model-based. The cheapest available model (selected via `config.select_models(role="dedup")`) is given all findings and asked to group them. Port the prompt shape from dvad core's `prompts.build_dedup_prompt` and response parser from `parser.parse_dedup_response`; simplify away spec-mode branching.
- Fallback path: deterministic. When the dedup model fails, or is unavailable, fall back to a simple similarity group — tokenize `issue` text, Jaccard overlap ≥ 0.6, or startswith/substring match on the first N words. Mark `dedup_skipped: true` in the response when the fallback runs without a model.
- Resolves spec Open Question #1: default is **model-based** (dedup call is cheap — Haiku or gpt-5-mini — and the quality difference on overlapping findings is noticeable). Deterministic is the failure fallback, not the default.

**Success check:** Three identical findings produced by three reviewers collapse to one with `consensus: 3, models_reporting: [a, b, c]`. Three genuinely distinct findings stay as three.

### Phase 6 — Output Rendering (half day)

**Deliverable:** `report_markdown` reads like a product, not a debug dump.

- `output.py` renders the markdown report: header, summary table, grouped findings (critical → low), reviewer errors section if any, cost/duration footer
- Format mirrors the "Agent Handoff Format" block in the spec — the markdown is designed to be pasted into the agent's own handoff message verbatim
- Same findings appear in JSON (for agents) and markdown (for humans) with no information asymmetry

**Success check:** A report from a real review pasted into a GitHub issue renders cleanly, is scannable in under 10 seconds, and makes the "no-review" alternative look careless by comparison.

### Phase 7 — MCP Server (1 day)

**Deliverable:** A Claude Code session with the MCP server configured can invoke `dvad_review`, `dvad_estimate`, and `dvad_config`.

- Use the official `mcp` Python SDK, stdio transport
- Tool 1 — `dvad_review`: parameters match spec §1 `dvad_review`; calls into `review.run_lite_review`; returns the JSON shape exactly as specified
- Tool 2 — `dvad_estimate`: reuses config + cost layers, no external calls, returns in milliseconds
- Tool 3 — `dvad_config`: returns current `config` state
- First-run handling: if no keys are detected, `dvad_review` returns `{"status": "setup_required", ...}` structured response. This is a **successful tool return**, not an MCP error — the calling harness should treat it as data the agent relays to the human.
- Progress signaling: emit MCP progress notifications at each reviewer completion boundary. If the client doesn't support progress, the notifications are no-ops; final result is unaffected.
- Budget tracking: in-memory cumulative spend per server process, reset on restart. Readable via `dvad_config`.

**Success check:** From Claude Code (terminal or VS Code extension), `@dvad` shows the three tools; invoking `dvad_review` against a plan argument returns structured findings in <30s.

### Phase 8 — Claude Code Skill (half day)

**Deliverable:** `skill/dvad.md` — a Claude Code skill definition that teaches the agent when and how to invoke adversarial review.

- YAML frontmatter: `name: dvad`, `description: Adversarial multi-model review checkpoint before declaring tasks done`, trigger keywords
- Body sections (all drawn from spec §2):
  - **When to invoke** — the auto-invoke trigger list (post-plan, post-implementation >50 lines, schema changes, new dependencies, security-adjacent code)
  - **When NOT to invoke** — typo fixes, formatting, docs-only, exploratory, budget exhausted
  - **How to call the MCP tools** — concrete example invocations
  - **How to process findings** — filter by severity/consensus, address critical/high, defer low with note
  - **Multi-agent delegation rule** — verbatim from spec: "If you are the top-level agent, you own the adversarial checkpoints..."
  - **Handoff message format** — the terse scannable format from spec §Agent Handoff Format

**Success check:** Dropping the skill into a Claude Code session and giving the agent a non-trivial coding task produces a handoff message that matches the format. Qualitatively: "would I want this on every task?" — yes.

### Phase 9 — Packaging and Install Path (half day)

**Deliverable:** A developer can install and wire this up with two commands plus an MCP config entry.

- `pipx install dvad-agent-native` (or `pipx install -e .` for local dev)
- MCP config snippet for Claude Code's `~/.claude/settings.json` / project-local config — provide copy-pasteable JSON in the README
- Skill install: `~/.claude/skills/dvad.md` (manual copy in v1; skill plugin infrastructure is v2)
- README sections: 30-second pitch, install, one demo, link to spec and roadmap

**Success check:** From a clean shell, follow the README exactly. End state: agent can invoke `dvad_review` successfully. No manual file editing beyond the two config additions.

### Phase 10 — Smoke Test Rig (ownership split per conversation Exchange 20)

This is the phase where Brian exits solo building and brings in a collaborator who lives in the IDE.

**What Brian + this agent can do alone (Phase 10a):**
1. Install the MCP server locally
2. Open VS Code with the Claude Code extension
3. Clone a small public repo (suggested: a Flask todo app, Express starter, or a simple Python CLI — small enough to understand in 20 minutes)
4. Configure the MCP server in the workspace
5. Give the agent a non-trivial task (e.g., "add input validation to the /login endpoint")
6. Watch the cycle: plan → dvad → revised plan → implementation → dvad → handoff
7. Verify mechanical correctness — server starts, tools register, calls complete, findings return, handoff renders

**What requires the v2 collaborator (Phase 10b):**
8. Judge whether the handoff *feels* right in a daily IDE flow — density, interruption cost, trust calibration
9. Report back: ship / iterate / this-specific-thing-is-off

**Explicit non-tasks for Brian:**
- Do not try to learn VS Code deeply — you need to open it, install an extension, use the Claude Code panel. That's it.
- Do not try to understand the test codebase's architecture — you need to give the agent a task and watch what dvad does with the result.
- Do not write tests for dvad itself during smoke testing — that was Phase 4/5/7. This is experience testing.

---

## 4. What To Port From dvad Core (Concrete Map)

| dvad core file | What to port | What to leave behind |
|---|---|---|
| `providers.py` | httpx call shape, retry/backoff, 529 budget, usage dict return | Thinking budgets, MiniMax, mode-dependent branching |
| `config.py` | Env key resolution pattern, XDG path handling, model dataclass shape | Multi-mode config, service management, GUI-specific fields |
| `dedup.py` | Dedup prompt shape, response-to-groups structure | Spec-mode branching, context overflow fallback (we'll use a simpler one) |
| `prompts.py` | Rubric-per-mode prompt structure, dedup prompt | Revision/author-response/rebuttal prompts |
| `cost.py` | Token estimator, per-model cost calc | Nothing — this file is already minimal |
| `output.py` | Markdown report structure inspiration | Round-2 exchange rendering, author response sections |

**Rule:** port means open the file, read it, understand the pattern, close it, and rewrite against the new package structure. Do not `from devils_advocate import ...`.

---

## 5. Testing Strategy

The test surface is deliberately small. The product's quality bar is "does it work in a real Claude Code session" — that's end-to-end smoke testing, not unit test count.

- **Unit tests** for pure functions: secrets regex, cost estimation, outcome derivation, category normalization, config precedence. Fast, deterministic.
- **Integration tests** with mocked httpx: partial failure paths, budget aborts, dedup fallback. No real API calls in CI.
- **Real-API smoke test** (manual, not in CI): a pytest fixture that runs a review against real providers when `DVAD_E2E=1` is set. Used sparingly — cost money.
- **Skip:** fuzz testing, load testing, golden-report comparisons (the reviewer models vary across runs; brittle).

Target: ~150 tests, runs in <10s without real API calls. Small by design.

---

## 6. Open Questions Carried Forward

These are unresolved at plan time and will be answered by building:

1. **Dedup default is model-based, fallback deterministic** — decided in Phase 5. If the cheapest dedup model adds >3s to the pipeline, revisit and default to deterministic with model-based as an opt-in.
2. **Reference file inference stays out of v1** — the agent passes `reference_files` explicitly; dvad does not crawl. Revisit if users report noise from context-less reviews.
3. **Single-provider diversity (spec OQ #3)** — when only one API key is present, dvad can still run two models from the same provider but surfaces a `diversity_warning` field. Not gated, just flagged. Revisit once adoption data exists.

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lite mode fails <30s target with 3 providers | Medium | High — product thesis breaks | Measure in Phase 4; if over, cut dedup to deterministic or trim prompts |
| Secrets regex false positives block legitimate reviews | Medium | Medium — workflow friction | Entropy gate + `redact` mode as escape hatch; document override |
| MCP progress notifications don't work in some clients | Medium | Low — silent success is still success | No-op fallback; don't depend on progress for correctness |
| Provider API shape drift between plan and ship | Low | Medium | httpx-direct means we see breakage as HTTP errors, not SDK exceptions; pin provider API versions in headers |
| Reviewer JSON output parsing fails inconsistently | Medium | Medium | Use JSON-mode on providers that support it; regex-salvage fallback; treat parse failure as a `ReviewerError`, not a crash |
| First-run `setup_required` gets treated as tool error by some MCP clients | Low | High — bad first impression | Return it as success-with-data, not an MCP error response; test against Claude Code specifically before ship |
| Build scope creeps toward v2 features | High | Critical — invisible-tool problem recurs | Spec §Non-Goals is the law. Roadmap exists so "good ideas" have a home without bloating v1 |

---

## 8. Explicit Non-Goals (Reminder)

Per spec §Non-Goals, the following are OUT for v1 and will be pushed back to if raised during build:

- IDE-native integration (gutter annotations, squigglies, extensions)
- CI/CD integration (GitHub Actions, PR bots)
- Hosted service / SaaS
- Changes to dvad core
- Automatic reference file discovery
- Custom rubrics via MCP
- Multi-turn review sessions
- Structured `parent_review_id` delta computation
- Batch / multi-artifact review
- Finding location hints (`file_path`, `approx_lines`)
- Anything on the `roadmap.md` v2/v3 lists

---

## 9. Success Criteria (from spec, restated for accountability)

Build is done when:

1. Two-command install works for a developer with at least two provider keys
2. Agent-invoked `dvad_review` returns structured findings in <30s for a <5K-token artifact
3. The handoff message with adversarial trail included is visibly better than without it — to the point where "done, tests pass" feels reckless by comparison
4. A contributor can read the codebase end-to-end in under 30 minutes
5. Meta-success: a dvad review of this plan (using the command above) produces findings that improve the plan

Criterion #5 runs immediately after this plan is written.

---

## 10. What Happens After Plan Approval

1. Run this plan through dvad (command at top). Fold findings into `plan.v2.md`. Possibly one more round.
2. Begin Phase 0. Produce a working install from an empty repo.
3. Progress phases in order; each phase's success check is the gate to the next.
4. At Phase 10a, pause and record a demo. Hand off to the v2 collaborator for Phase 10b judgment.
5. Ship v1 when Phase 10 passes. Post the 30-second demo + install line to the venues that matter (HN, r/ClaudeAI, r/programming, LinkedIn for the "proof of thinking" framing).

The distance from here to a shipped v1 is measured in weeks, not months. The engine exists in dvad core; this is a focused, small rewrite behind an MCP interface. The invisible-tool risk is solved by the install line and the demo, not by more code.
