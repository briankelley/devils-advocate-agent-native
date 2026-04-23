# dvad-agent-native v1 — Implementation Plan (v2)

**Status:** Revised after adversarial review — pairings 1 (GPT-5.4 + GLM-5.1) and 2 (Claude-Opus-4.6 + Gemini-3.1-pro-preview). 36 of 43 findings folded in; 7 escalated items resolved with explicit decisions documented in §11.
**Date:** 2026-04-23
**Spec reference:** `docs/spec.v3.md`
**Supersedes:** `docs/plan.v1.md`

---

## dvad Review Command

```bash
/media/kelleyb/DATA2/code/tools/devils-advocate/.venv/bin/dvad review \
  --mode plan --project dvad-v1-agent-native \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/plan.v2.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/spec.v3.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/providers.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/config.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/dedup.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/output.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/prompts.py
```

---

## 1. Guiding Constraints

These are the non-negotiables the build measures itself against. If any decision breaks one of these, the decision is wrong.

1. **Small, focused, readable in one sitting.** A skilled Python developer should be able to hold the architecture in their head after a single reading. No module added without a clear reason. No abstraction introduced ahead of a second concrete use case. Expected landing: ~1,200–1,500 LoC of production Python excluding tests — not as a cap, but as a sanity check. Exceeding it is a signal to ask "what's paying for these lines?" not a trigger to refuse work the reviewers proved was necessary.
2. **Standalone.** No import dependency on dvad core. Port patterns; do not wrap.
3. **Lite mode only.** No governance, no author response, no revision, no rebuttals. Full-mode depth lives in dvad core; a bridge is a future question.
4. **Stateless review pipeline.** Each `dvad_review` call is a pure function of its inputs. Persistence is write-only bookkeeping (budget state, audit trail), never a read dependency for correctness.
5. **Zero-config with respectful overrides.** Works with just API keys in env — including proxy base URLs for developers using OpenRouter, Groq, or local models. `models.yaml` is an override path, never a prerequisite.
6. **Advisory, not gate.** Every outcome — including `critical_found` — is information, not a stop signal. The word choice in error messages, outcomes, and logs reflects this.
7. **Secrets never leave without consent.** Pre-scan is a hard gate before any external API call. Covers the full outbound payload: artifact + instructions + reference file contents. No exceptions for performance.

---

## 2. Architecture at a Glance

```
devils-advocate-agent-native/
├── pyproject.toml                  (pipx-installable, entry points for CLI + MCP server)
├── README.md                       (install line, one demo, link to spec)
├── LICENSE                         (MIT)
├── docs/
│   ├── spec.v3.md                  (frozen product definition)
│   ├── plan.v2.md                  (this file)
│   ├── roadmap.md                  (v2/v3/rejected)
│   └── conversation.01.md          (strategic origin, for future context)
├── src/dvad_agent/
│   ├── __init__.py
│   ├── __main__.py                 (python -m dvad_agent → CLI)
│   ├── types.py                    (dataclasses: Finding, ReviewResult, ModelConfig,
│   │                                ToolResponse discriminated union, category
│   │                                normalization table)
│   ├── config.py                   (key + base-URL detection, model defaults,
│   │                                logging setup, diversity warning logic)
│   ├── budget.py                   (daily spend tracking with disk persistence,
│   │                                calendar-day rollover in local time, fcntl
│   │                                file locking, warning thresholds)
│   ├── cost.py                     (token estimation, pricing table, context-window
│   │                                preflight)
│   ├── providers.py                (httpx calls: Anthropic, OpenAI-compatible,
│   │                                OpenAI Responses, Google — see §4 Port Map)
│   ├── secrets.py                  (string-based regex scan + entropy check, abort
│   │                                and redact modes, DVAD_SECRETS_MODE override)
│   ├── prompts.py                  (rubric per artifact_type, dedup prompt)
│   ├── review.py                   (lite-mode orchestrator: as_completed fan-out,
│   │                                pipelined dedup, deadline enforcement, outcome
│   │                                derivation, reference file handling)
│   ├── dedup.py                    (model-based primary, deterministic fallback)
│   ├── output.py                   (markdown renderer + JSON shaping)
│   ├── server.py                   (MCP stdio server, 3 tools, progress signals,
│   │                                httpx client lifespan)
│   └── cli.py                      (developer testing surface — grows to fit
│                                    phase-gate needs, no artificial LoC cap)
├── skill/
│   └── dvad.md                     (Claude Code skill definition)
├── scripts/
│   └── install.py                  (dvad-agent install bootstrap — writes MCP
│                                    config, copies skill)
└── tests/
    ├── test_secrets.py
    ├── test_config.py
    ├── test_budget.py              (rollover, threshold warnings, file locking)
    ├── test_cost.py                (pricing table, context-window checks)
    ├── test_review.py              (partial failure paths, outcome+degraded,
    │                                deadline enforcement, reference file flow)
    ├── test_dedup.py               (model path mocked, deterministic algorithm
    │                                deterministic across runs)
    ├── test_prompts.py             (rubric per artifact_type renders)
    ├── test_output.py              (markdown structure, JSON shape, finding order)
    ├── test_server.py              (MCP tool schemas per status variant, contract
    │                                tests against JSON-schema fixtures)
    └── test_paths.py               (path validation: ../../, symlink escape,
                                     home-dir targets, size caps)
```

**Why Python:** dvad core is Python; provider patterns port cleanly; MCP has a first-party Python SDK (`mcp` package); pipx is the cleanest single-command install path.

**Why httpx direct (not provider SDKs):** no SDK version lock-in, tiny dependency footprint, async-native, provider API changes surface as HTTP errors instead of SDK exceptions.

**Why a separate CLI:** for phase-gate verification during the build (see §3 Phase 0 rationale) and ongoing developer debugging. The CLI is development infrastructure, not a product surface. It is never the thing we optimize for adoption or polish; it's the tool that lets us verify each phase before wiring it into MCP.

---

## 3. Work Breakdown

Phases are ordered so each one produces a testable deliverable. Do not start phase N+1 until phase N runs clean.

### Phase 0 — Scaffolding

**Deliverable:** Empty-but-installable package. `pipx install -e .` works; `dvad-agent --help` prints; `dvad-agent-mcp` starts and exits cleanly on EOF.

- `pyproject.toml` with `project.scripts` entries for CLI (`dvad-agent`), MCP server (`dvad-agent-mcp`), and install bootstrap (`dvad-agent install` as a subcommand)
- Dependencies: `httpx`, `mcp`, `pyyaml`. That's the full list. No embedding libraries, no SDKs, no redis.
- Package skeleton: every module listed above exists with a docstring and maybe a `pass`
- `README.md` stub with the install line and a "coming soon" demo placeholder
- `LICENSE` (MIT)
- `.gitignore`, `.editorconfig`, pre-commit with `ruff` + `black`

**Success check:** `pipx install -e .` resolves and both entry points execute.

### Phase 1 — Types, Config, Logging, Budget Scaffolding

**Deliverable:** `dvad-agent config` prints a JSON blob describing what's available; `dvad-agent budget` shows current day's spend; logs go to stderr.

**Types (`types.py`):**

- `ModelConfig` — provider, model_id, api_key, api_base, cost_per_1k_input, cost_per_1k_output, context_window, use_responses_api (bool, for OpenAI /v1/responses dispatch), thinking_disabled (bool, for Anthropic)
- `ProviderKey` — provider name, api_key, optional api_base
- `Severity` — enum: critical, high, medium, low, info
- `Category` — closed enum, 9 values total including `other`: correctness, security, performance, reliability, testing, maintainability, compatibility, documentation, other
- `Outcome` — enum (content severity only): `clean`, `caution`, `critical_found`
- `Finding` — severity, consensus, category, category_detail, issue, detail, models_reporting
- `ReviewerError` — model_name, provider, error_type, message, raw_response (preserved for parse failures)
- `SecretMatch` — pattern_type, approx_line_range, channel (artifact/instructions/reference_file)
- `BudgetStatus` — spent_usd, cap_usd, remaining_usd, warning_level (`none` | `soft` | `hard`), day (YYYY-MM-DD string)
- `ReviewResult` — review_id, parent_review_id, artifact_type, mode, outcome, degraded (bool flag, independent of outcome), diversity_warning (bool), models_used, duration_seconds, cost_usd, findings, summary, reviewer_errors, dedup_method (`model` | `deterministic`), dedup_skipped (bool), redacted_locations (list of `SecretMatch` shape with pattern_type + approx_line_range; never contains actual secret values), original_artifact_sha256, budget_status, report_markdown
- `ToolResponse` — **discriminated union**. Every MCP tool return has a required `status` field:
  - `ok` — review completed, full `ReviewResult` in body
  - `setup_required` — no keys detected, includes setup_steps and docs_url
  - `skipped_budget` — daily cap hit, includes BudgetStatus
  - `skipped_secrets` — secrets detected in abort mode, includes matches (pattern type + location, not values)
  - `oversize_input` — artifact + context exceeds model context window, includes fit details per model
  - `failed_review` — <2 reviewers succeeded, includes reviewer_errors
  - `degraded` — NOT a status. Always a flag on an `ok` response.
- `CATEGORY_NORMALIZATION_TABLE` — static dict (~20 entries) mapping common variants ("vulnerability" → "security", "bug" → "correctness", "speed" → "performance", etc.) applied case-insensitively before dedup; unknown values → `other` with the raw string preserved in `category_detail`

**Config (`config.py`):**

- Env-key detection: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` / `GEMINI_API_KEY`
- **Base URL detection:** `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL` — if present, propagated into `ModelConfig.api_base` so proxy users (OpenRouter, Groq, vLLM) get zero-config support without editing a yaml file
- Default model table per provider (reviewer + dedup roles):
  - Anthropic: `claude-sonnet-4-6` (reviewer), `claude-haiku-4-5-20251001` (dedup, non-reasoning)
  - OpenAI: `gpt-5` (reviewer, `use_responses_api=True`), `gpt-4o-mini` (dedup, non-reasoning)
  - Google: `gemini-2.5-pro` (reviewer), `gemini-2.5-flash` (dedup, non-reasoning)
  - **Dedup models are chosen for speed, not reasoning.** See §3 Phase 5 latency rationale.
- **`minimum_met` logic:** true when ≥2 distinct reviewer-role models are available, even from the same provider. With a single Anthropic key, `claude-sonnet-4-6` + `claude-opus-4-7` satisfy the minimum with `diversity_warning: true`.
- `diversity_warning` surfaced in `dvad_config`, `dvad_estimate`, and `dvad_review` responses whenever all reviewers share a provider
- `models.yaml` override precedence: project-local → `$DVAD_HOME` → XDG
- Budget defaults: `$2.00/review`, `$50.00/day`; override via `DVAD_BUDGET_PER_REVIEW` / `DVAD_BUDGET_DAILY`; **`DVAD_BUDGET_DAILY=0` disables the daily cap entirely** for power users who don't want any daily guardrail
- Secrets handling: single authoritative `secrets_handling` field, default `abort`, override via `DVAD_SECRETS_MODE` env var (`abort` | `redact` | `skip`)
- **Logging setup:** stdlib `logging` under `dvad_agent` namespace; `StreamHandler(sys.stderr)` only; default INFO; DEBUG under `DVAD_LOG_LEVEL=debug`. Root logger is explicitly reconfigured at server startup to prevent accidental stdout output (would corrupt MCP stdio transport)

**Cost (`cost.py`):**

- Token estimator (4 chars per token heuristic, ported unchanged from dvad core)
- `estimate_cost(model, in_tokens, out_tokens) -> float`
- `check_context_window(model, text) -> (fits: bool, est_tokens: int, limit: int)` — ported pattern from dvad core's `cost.py`

**Budget (`budget.py`):**

- Daily spend persisted to `~/.local/share/devils-advocate/budget/YYYY-MM-DD.json` (file mode 0600, directory 0700)
- **Calendar day in local timezone.** Midnight local-time rollover. No override — timezone handling adds configuration fatigue that isn't warranted for v1.
- On each review: open today's file (or create), `fcntl.flock` around check-and-decrement, compare cumulative + this-review's-estimate against cap, write back
- **Warning thresholds:** `warning_level` in BudgetStatus is `soft` at ≥70% of cap, `hard` at ≥85%. Pattern mirrors Claude Code's context-remaining warnings — subtle, non-interruptive, surfaced in the response for the agent to include in its handoff.
- `DVAD_BUDGET_DAILY=0` disables the cap entirely but continues tracking spend (so elite users can watch their own bill without being blocked)
- Corrupted/missing budget file → start fresh at $0, log the event, continue
- Disk full on write → log, proceed with the review; bookkeeping hiccup does not block the user's work
- CLI: `dvad-agent budget` prints the current day's BudgetStatus

**Success check:** With only `ANTHROPIC_API_KEY` set, `dvad-agent config` reports 1 provider, `minimum_met: true`, `diversity_warning: true`, and lists the two Anthropic models available. With two provider keys, `diversity_warning: false`. With `OPENAI_BASE_URL` set plus `OPENAI_API_KEY`, the OpenAI provider uses the custom base. `dvad-agent budget` shows today's file exists and is readable.

### Phase 2 — Provider Layer

**Deliverable:** `dvad-agent probe --model <name>` returns a short response and usage dict for any model in the default table, for each of the three providers.

**Provider functions (`providers.py`):**

- `call_anthropic(client, model, system, user, max_tokens) -> (text, usage)` — httpx to `/v1/messages`; **explicitly sets `thinking: {type: "disabled"}`** when `model.thinking_disabled` is True (which is the v1 default for reviewer roles, since lite mode doesn't need reasoning traces); tool-use / structured-output support for JSON enforcement
- `call_openai_compatible(client, model, system, user, max_tokens) -> (text, usage)` — httpx to `{api_base or default}/chat/completions`; `response_format: {type: "json_object"}` when JSON is requested
- **`call_openai_responses(client, model, system, user, max_tokens) -> (text, usage)` — httpx to `{api_base}/responses`; ported from dvad core's `call_openai_responses`.** Required for gpt-5 (reasoning series uses `/v1/responses`, not `/v1/chat/completions`). Distinct structured-output mechanism.
- `call_google(client, model, system, user, max_tokens) -> (text, usage)` — **NET-NEW code, not a port.** dvad core has no Google implementation. Target: AI Studio Gemini API v1beta (`generateContent` endpoint), `x-goog-api-key` header, `contents[].parts[]` request format, `usageMetadata.promptTokenCount` / `candidatesTokenCount` for usage. `responseMimeType: "application/json"` for structured output. Vertex AI / OAuth is explicitly deferred. **Before implementing from scratch, evaluate Google's OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai/`) — if it satisfies our usage, we reuse `call_openai_compatible` with an overridden `api_base` and skip writing Gemini-native code entirely.**
- `call_with_retry(...)` — exponential backoff with jitter, 529-specific budget, ported from dvad core
- **Dispatcher `call_model(model, system, user) -> (text, usage, cost)`** that routes by `model.provider` and `model.use_responses_api` flag

**Three-tier JSON parsing strategy:**

1. Provider-native structured output where supported (Anthropic tool_use, OpenAI `response_format`, Google `responseMimeType`)
2. If that fails or returns markdown-wrapped output, `sanitize_json_output()` strips ```json``` fences and extracts the first valid JSON block via regex
3. If both fail, the reviewer's output becomes a `ReviewerError` with `raw_response` preserved for debugging, counted against the ≥2-success threshold — not silently dropped

**httpx.AsyncClient lifecycle:**

- MCP path: single client created at server startup via MCP SDK's lifespan hook (or contextmanager wrapper), stored on server state, shared across all review calls, closed on shutdown with a bounded drain period for in-flight work. After drain, any remaining tasks are cancelled.
- CLI path: client created per invocation inside an `async with httpx.AsyncClient() as client:` block.

**Success check:** `dvad-agent probe --model claude-sonnet-4-6` works with thinking explicitly disabled (no surprise reasoning-token inflation); `--model gpt-5` correctly dispatches to the Responses endpoint; `--model gemini-2.5-pro` returns a response from either the OpenAI-compat endpoint or the native Gemini API, whichever we chose.

### Phase 3 — Secrets Pre-Scan

**Deliverable:** `scan(content: str) -> list[SecretMatch]` works on arbitrary strings; `dvad-agent scan --file path/to/artifact.md` is a convenience wrapper that reads the file and calls `scan()` on the content.

- **String-based scanner**, not file-based. `scan(content: str)` is the core function. The CLI `--file` flag reads the file and passes its content to `scan()`. MCP receives `artifact` as a string directly.
- Pattern set: AWS keys (`AKIA[0-9A-Z]{16}`), `BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY`, Stripe live keys, GitHub PATs, Slack tokens, generic `KEY=high-entropy-value` heuristic, connection strings with embedded passwords
- File-path reference heuristics: mentions of `.env`, `credentials.json`, `secrets.yaml`, key vault paths
- Entropy gate on `KEY=VALUE` lines to suppress template placeholders and test fixtures
- Two modes: `abort` (default) and `redact`
  - `redact` replaces matches with stable placeholders (`[REDACTED_1]`, `[REDACTED_2]`) and returns a mapping held in memory **only** — never persisted, never included in response bodies. The response includes `redacted_locations` (pattern type + line range only, no secret values) and `original_artifact_sha256` so the human can resolve placeholders against their local copy.
- **Third mode `skip`:** only selectable via `DVAD_SECRETS_MODE=skip` env var — an escape hatch for persistent false positives in zero-config setups. **Never** a per-call tool parameter; the security control must not be prompt-downgradable by an LLM-driven caller.
- Hard rule: the secrets scan runs on the **full outbound payload** (artifact + instructions + concatenated reference-file contents) immediately before each `call_model` invocation. Not on the raw input, not on the artifact alone — on the exact bytes about to leave the machine.

**Success check:** A crafted artifact containing each pattern is aborted or cleanly redacted. A crafted artifact with secrets in `instructions` or `reference_files` is caught by the gate, not just in the primary artifact. A crafted "false positive" artifact (documentation about secret patterns, test fixtures with low-entropy values) doesn't trip. `DVAD_SECRETS_MODE=redact` converts an abort to a redact without config file edits.

### Phase 4 — Lite-Mode Review Orchestrator

**Deliverable:** `dvad-agent review --artifact-type plan --file plan.md` returns a `ReviewResult` JSON with findings, outcome, degraded flag, cost, and latency breakdown.

**Pipeline in `review.py`:**

```
async def run_lite_review(
    artifact: str,
    artifact_type: str,
    context: ReviewContext,
    budget_limit: float | None,
    parent_review_id: str | None,
    deadline_seconds: float = 45.0,
) -> ToolResponse: ...
```

1. **Load reference files** (if any): read each from disk; reject with a structured warning any path that resolves outside `repo_root` after symlink resolution, any absolute path, any `..` traversal, or any file exceeding a per-file size cap. If `repo_root` is not supplied, `reference_files` is rejected entirely.
2. **Assemble outbound payload:** artifact + instructions + concatenated reference-file contents with `=== REFERENCE FILE: {path} ===` delimiters.
3. **Secrets pre-scan** against the full assembled payload (§7 Phase 3). Abort or redact per mode. If `oversize_input`, return that status.
4. **Context-window preflight:** compute token fit for each reviewer prompt and the dedup prompt. If any exceeds its model's configured window, trim reference files from the end first, then truncate the artifact if necessary, then return `oversize_input` if still over.
5. **Budget preflight:** compute estimated cost; compare against per-review budget AND today's remaining daily spend (under `fcntl.flock`). If over either, return `skipped_budget`.
6. **Build rubric prompt** for `artifact_type` (`prompts.py`).
7. **Fan out reviewers via `asyncio.as_completed`** (not `gather` — `gather` can't emit per-completion progress signals). Emit an MCP progress notification as each reviewer resolves.
8. **Pipeline dedup:** as soon as 2/3 reviewers complete, kick off the dedup call on what we have. If the third reviewer resolves before dedup returns, merge its findings into the in-flight dedup (or re-dedup after — implementation choice, measured in Phase 5).
9. **Apply partial-failure rule:** ≥2 reviewers must succeed; if not, return `failed_review` with `reviewer_errors`. Parse failures count as ReviewerErrors against this threshold.
10. **Normalize categories** through `CATEGORY_NORMALIZATION_TABLE` before dedup.
11. **Severity & category merge rules:**
    - Merged severity = max across contributing findings (any `critical` wins)
    - Merged category = modal across contributors, ties broken by highest-severity contributor's category
    - `consensus` = count of distinct reviewer models reporting
    - `models_reporting` preserved verbatim
12. **Derive outcome (content severity only):**
    - Any `critical` finding → `outcome: "critical_found"`
    - Any `high` finding (and no critical) → `outcome: "caution"`
    - Otherwise → `outcome: "clean"`
13. **Derive `degraded` flag (coverage health, independent field):**
    - `degraded: true` when ≥1 reviewer failed AND the remaining reviewers lack cross-provider diversity (e.g., two Anthropic models succeed but OpenAI fails)
    - Single failure with remaining diverse coverage → `degraded: false`
    - An agent parsing the response sees BOTH signals independently; the content severity is never masked by a coverage issue.
14. **Deadline enforcement:** overall `review_deadline` (default 45s, configurable) via `asyncio.wait(..., timeout=remaining)`. On deadline, cancel stragglers, treat them as `ReviewerError` with `error_type: "deadline_exceeded"`, apply the ≥2-success rule. Progress notifications include remaining budget.
15. **Sub-budgets:** ~25s for fan-out, ~10s for dedup, ~10s of slack.
16. **Render `report_markdown`** (`output.py`) — see §3 Phase 6.
17. **Assemble `ReviewResult`**, wrap in `ToolResponse{status: "ok"}`, include BudgetStatus and diversity_warning in the response.
18. **Persist (opt-in):** if `DVAD_PERSIST_REVIEWS=1`, write metadata-only review to `~/.local/share/devils-advocate/reviews/{review_id}/` (file mode 0600, dir 0700). Redaction mappings are **never** persisted. Raw artifact persistence is a separate opt-in flag.

**Latency Budget (explicit):**

| Stage | p50 | p95 |
|---|---|---|
| Reference file load + secrets scan + preflight | <1s | 2s |
| Fan-out (3 reviewers in parallel, thinking off, JSON mode) | 12–15s | 20–25s |
| Dedup (non-reasoning fast model, pipelined from 2/3 complete) | 0–2s non-overlapped | 3–5s |
| Category normalization, severity merge, outcome derivation | <100ms | <500ms |
| Render markdown + assemble response | <200ms | <500ms |
| **Total** | **~14–18s** | **~25–31s** |

The <30s target is comfortable at p50 and tight-but-achievable at p95. Load-bearing assumptions: (a) thinking disabled on Anthropic reviewers, (b) reviewer output hard-capped at ~1500 tokens, (c) dedup model is non-reasoning, (d) dedup is pipelined from 2/3-complete boundary. Any of these flipping blows the budget.

**Success check:** A plan artifact with a known weakness produces ≥1 finding running against two real providers. Duration stays under 30s for a 5K-token plan. Outcome derives correctly from findings (`critical_found` on any critical; `caution` on high-no-critical; `clean` otherwise). `degraded: true` when reviewer failure collapses cross-provider diversity. BudgetStatus is present and reflects today's spend.

### Phase 5 — Dedup

**Deliverable:** Three reviewers' overlapping findings collapse into a single entry with `consensus: 3`. Three distinct findings stay as three.

**Primary: model-based dedup.**

- Uses the cheapest available **non-reasoning** model per provider (Anthropic: Haiku; OpenAI: gpt-4o-mini; Google: gemini-2.5-flash). Reasoning models like `gpt-5.4-nano` are rejected for dedup because reasoning adds 5–15s of latency to a task that is pattern-matching, not synthesis. Empirical reference: recent dvad core reviews using `gpt-5.4-nano` for dedup showed $0.004–$0.011 cost per dedup call, corresponding to ~5–15s wall-clock at nano-reasoning speeds. Non-reasoning models on the same payload land at 2–4s.
- Prompt shape ported from dvad core's `build_dedup_prompt` (see `dedup.py` and `prompts.py` in core). Simplified — no spec-mode branching.
- Pipelined from 2/3-reviewers-complete to overlap with the tail reviewer's wall-clock.

**Fallback chain (per spec §10):**

- **If the designated dedup model fails** → retry on the cheapest available reviewer model.
- **If no model is available for dedup** → deterministic grouping.
- **If dedup is running and exceeds its sub-budget** → cancel, fall to deterministic.

**Deterministic algorithm (precisely specified, reproducible across implementations):**

1. **Category-aware grouping:** findings are only compared within the same `category` bucket. This prevents cross-category false merges (e.g., "missing auth check on login" in `security` vs "missing test coverage for login" in `testing` share the word "login" but should never merge).
2. **Tokenize:** lowercase the `issue` field, split on `\W+` (Unicode word boundaries), drop empty tokens.
3. **Normalize:** strip a short stop-word list (a, an, the, is, in, on, of, and, or).
4. **Merge rule:** two findings merge if either
   - Jaccard similarity on unigram sets ≥ 0.6, OR
   - First 5 non-empty normalized tokens of `issue` are identical
5. **Mark result:** `dedup_method: "deterministic"`, `dedup_skipped: true`. The markdown report notes reduced consolidation quality.

Within-category false merges (e.g., "SQL injection in login" vs "SQL injection in payment" at Jaccard ≥ 0.6) are an explicitly acknowledged quality trade-off for the deterministic fallback. The `dedup_skipped` flag tells downstream consumers to expect this.

**Success check:** Three identical findings from three reviewers collapse to one with `consensus: 3, models_reporting: [a, b, c], dedup_method: "model"`. Three genuinely distinct findings stay separate. When the dedup model is forced offline in tests, the fallback chain executes deterministically and `dedup_method: "deterministic"` appears in the response.

### Phase 6 — Output Rendering

**Deliverable:** `report_markdown` reads like a product, not a debug dump. JSON and markdown convey the same information.

- `output.py` renders markdown with: header, summary table (counts by severity), BudgetStatus footer, `diversity_warning` banner if applicable, grouped findings (critical → low), reviewer-errors section if any, cost + duration footer, `degraded` banner if `degraded: true`
- Format mirrors spec §Agent Handoff Format — the markdown is designed to be pasted verbatim into the agent's own handoff message
- JSON and markdown share one source-of-truth dataclass; the renderer is the only place that differs
- **Redaction handling in output:** when redact mode fires, the markdown includes a clear section listing `redacted_locations` (pattern type + line range) and `original_artifact_sha256` so the human can cross-reference their local copy. The redaction mapping itself never appears in output.

**Success check:** A report from a real review pasted into a GitHub issue renders cleanly, is scannable in under 10 seconds. Redacted reviews show placeholder locations without leaking secret values. Degraded reviews show both outcome severity and coverage banner distinctly.

### Phase 7 — MCP Server

**Deliverable:** A Claude Code session with the MCP server configured can invoke `dvad_review`, `dvad_estimate`, and `dvad_config` and receive properly-shaped responses for every status variant.

- Official `mcp` Python SDK, stdio transport
- **All three tools return the `ToolResponse` discriminated union.** Every success variant AND every non-review-complete variant has a fixed JSON schema. Clients branch on `status`.
- Tool 1 — `dvad_review`: parameters match spec §1; calls into `review.run_lite_review`; returns `ToolResponse` with the discriminated `status`. `setup_required` is returned as a successful tool response (data the agent relays), **not** an MCP protocol error — this prevents MCP clients that surface errors differently from breaking the first-run experience.
- Tool 2 — `dvad_estimate`: reuses config + cost + context-window preflight; no external calls; returns in milliseconds. Includes per-model fit results.
- Tool 3 — `dvad_config`: returns current config state — detected providers, base URLs, available models, budget defaults, secrets handling mode, diversity warning status.
- **Progress notifications:** emitted at each reviewer completion boundary (enabled by `asyncio.as_completed` in review.py) and at dedup start/end. If the MCP client doesn't support progress, the notifications are no-ops; final result is unaffected.
- **Server lifecycle:** single `httpx.AsyncClient` created at startup via MCP lifespan hook (or contextmanager fallback), closed on shutdown after a bounded drain period (e.g., 10s) during which in-flight reviews complete. Remaining tasks cancelled. Budget file locks released cleanly on shutdown.

**Success check:** From Claude Code (terminal or VS Code extension), `@dvad` shows the three tools. Invoking `dvad_review` on a plan artifact returns structured findings in <30s. Invoking with zero API keys returns `status: "setup_required"` as data, not as an MCP error. Invoking with budget exhausted returns `status: "skipped_budget"` with BudgetStatus.

### Phase 8 — Claude Code Skill

**Deliverable:** `skill/dvad.md` teaches the agent when and how to invoke adversarial review and how to surface budget warnings.

- YAML frontmatter: `name: dvad`, description, trigger keywords
- Body sections (drawn from spec §2):
  - **When to invoke** — post-plan, post-implementation (>50 lines changed, schema changes, new dependencies, security-adjacent code)
  - **When NOT to invoke** — typo fixes, formatting, docs-only, exploratory, budget exhausted
  - **How to call the MCP tools** — concrete example invocations
  - **How to process findings** — filter by severity and consensus; address critical/high; defer low with note
  - **How to handle each ToolResponse status variant** — ok/setup_required/skipped_budget/skipped_secrets/oversize_input/failed_review — the agent relays `setup_required` as human-readable instructions, reports `skipped_*` in the handoff, etc.
  - **Multi-agent delegation rule** (verbatim from spec): the top-level agent owns the adversarial checkpoints; sub-agent internal checks don't replace it
  - **Handoff message format** — terse scannable format from spec §Agent Handoff Format; includes a one-liner for `budget_status.warning_level` when non-`none`, and a banner when `degraded: true`

**Success check:** A Claude Code session with the skill installed, given a non-trivial coding task, produces a handoff that matches the format, includes the adversarial trail, surfaces budget warnings inline when they fire, and notes degraded coverage when applicable.

### Phase 9 — Packaging and Install

**Deliverable:** A developer installs with two commands.

```
pipx install dvad-agent-native
dvad-agent install
```

The `install` bootstrap subcommand (`scripts/install.py` invoked by the CLI):

- Writes the MCP server entry to Claude Code's config (default `~/.claude/settings.json` or project-local equivalent); creates a backup first; supports `--dry-run`
- Copies `skill/dvad.md` to `~/.claude/skills/dvad.md`
- On any step failure, prints the exact JSON/file to paste as a fallback so the user can complete manually

README sections: 30-second pitch, install (two commands), one demo, link to spec and roadmap, call-out that the CLI exists for development and is not the product surface.

**Success check:** From a clean shell, following the README exactly gets a working install — agent can invoke `dvad_review` with no manual file editing.

### Phase 10 — Smoke Test

Ownership split per conversation Exchange 20.

**Phase 10a (Brian + this agent, mechanical correctness):**

1. Install MCP server locally
2. Open VS Code with Claude Code extension
3. Clone a small public repo (Flask todo, Express starter, etc.)
4. `dvad-agent install` in the workspace
5. Give the agent a non-trivial task
6. Watch the cycle: plan → dvad → revised plan → implementation → dvad → handoff
7. Verify: server starts, tools register, calls complete, findings return, handoff renders, budget tracks, degraded flag fires in injected failure

**Phase 10b (v2 collaborator, experience judgment):**

8. Does the handoff feel right in daily IDE flow?
9. Ship / iterate / this-specific-thing-is-off

**Explicit non-tasks for Brian:** don't deep-learn VS Code; don't deep-study the test repo's architecture; don't write tests for dvad itself during smoke testing.

---

## 4. Port Map (Revised)

| dvad core file | What to port | Status |
|---|---|---|
| `providers.py` — `call_anthropic` | httpx call shape, retry/backoff, 529 budget, usage dict, ability to **explicitly disable** thinking | Port |
| `providers.py` — `call_openai_compatible` | httpx to `/chat/completions`, usage attribution | Port |
| `providers.py` — `call_openai_responses` | httpx to `/responses` — **required** for gpt-5 reasoning series | Port (previously missed in v1) |
| `providers.py` — `call_google` | — | **Net-new code.** dvad core has no Gemini implementation. Evaluate OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai/`) before writing from scratch. |
| `config.py` | Env-key resolution pattern, XDG path handling, `ModelConfig` dataclass shape | Port |
| `dedup.py` | Dedup prompt shape, response-to-groups structure, `format_points_for_dedup` helper | Port |
| `prompts.py` | Rubric-per-mode prompt structure, dedup prompt | Port (adapt per spec artifact_type list) |
| `cost.py` | Token estimator, `check_context_window` utility | Port |
| `output.py` | Markdown report structure inspiration | Port as inspiration |
| `parser.py` | JSON parsing patterns, `sanitize_json_output` pattern | Port minimal |

**Rule:** port means read, understand the pattern, close the file, rewrite against the new package structure. Do not `from devils_advocate import ...`.

---

## 5. Testing Strategy

Target: ~200 tests total across unit, integration-with-mocks, and schema contract. Runs in <10s without real API calls. Small by design; the real quality bar is end-to-end smoke testing in Claude Code.

**Unit tests** (pure functions):
- Secrets regex (positive + negative + entropy gate)
- Cost estimation, context-window checks
- Outcome derivation matrix (all severity + degraded combinations)
- `degraded` flag logic (cross-provider diversity computation)
- Category normalization table
- Severity/category merge rules
- Deterministic dedup algorithm (reproducible across runs)
- Budget file I/O (calendar day rollover, threshold transitions, `DVAD_BUDGET_DAILY=0` behavior)
- Path validation (`../..`, symlinks escaping `repo_root`, absolute paths, size caps)
- Diversity warning derivation

**Integration tests** (mocked httpx):
- Partial failure paths (0, 1, 2, 3 reviewers failing)
- Budget abort (per-review and daily)
- Dedup model failure → reviewer-model fallback → deterministic fallback
- Deadline exceeded → stragglers cancelled → ≥2 success rule applied
- JSON parse failure → `ReviewerError` with `raw_response` preserved
- Secrets detected in each channel (artifact, instructions, reference_files)
- `oversize_input` trigger with real context-window math

**Schema contract tests** (pinned JSON-schema fixtures):
- `ok` response
- `setup_required` response
- `skipped_budget` response
- `skipped_secrets` response (abort mode)
- `oversize_input` response
- `failed_review` response
- `ok` response with `degraded: true`
- `ok` response with `dedup_method: "deterministic"`

Any schema drift breaks a contract test; this is how we catch the "silent field rename" class of bugs that plagues MCP tool consumers.

**Real-API smoke test** (manual, `DVAD_E2E=1`): a pytest fixture that runs a review against real providers. Used sparingly; costs money.

---

## 6. Open Questions Carried Forward

1. **Dedup default = model-based with fast non-reasoning models** — resolved in Phase 5 with empirical latency reasoning. Deterministic stays as fallback per spec §10.
2. **Reference file inference stays out of v1.** Agent passes `reference_files` explicitly; dvad does not crawl.
3. **Single-provider diversity** — runs with `diversity_warning: true`, doesn't gate. Revisit once adoption data exists.
4. **Google provider: OpenAI-compat endpoint vs native Gemini API** — decide in Phase 2 based on a 30-minute evaluation of the compat endpoint. Prefer compat if it satisfies our needs (zero net-new code).

---

## 7. Risk Register (Revised)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| p95 review latency exceeds 30s | Medium | High | Explicit stage budgets (§3 Phase 4), non-reasoning dedup models, pipelined dedup from 2/3-complete, deadline enforcement with partial-result semantics |
| Secrets regex false positives block legitimate reviews | Medium | Medium | Entropy gate; `redact` mode; `DVAD_SECRETS_MODE=skip` env escape hatch for zero-config users |
| MCP progress notifications don't work in some clients | Medium | Low | `as_completed` still drives correctness; no-op fallback for progress |
| Provider API shape drift | Low | Medium | httpx direct = breakage surfaces as HTTP errors, not SDK exceptions; pin API versions in headers; `probe` command for explicit model validation |
| JSON output parsing fails inconsistently | Medium | Medium | Three-tier strategy (native JSON mode → strip fences → `ReviewerError`); `raw_response` preserved |
| First-run `setup_required` treated as tool error by some MCP clients | Low | High | Return as success-with-data, not an MCP protocol error; contract test validates this |
| Path traversal via caller-supplied `reference_files` | Medium | High | `realpath` resolution; must resolve under `repo_root`; reject absolute paths, `..`, symlink escapes; size cap; test suite covers `../../etc/passwd`, symlink hops, `~/.ssh/*` |
| Concurrent MCP servers race on daily budget file | Low | Low | `fcntl.flock` around check-and-decrement; accept tiny over-spend in the extreme edge case of lock contention; not a protective feature, just bookkeeping |
| Google provider implementation cost underestimated | Medium | Medium | Acknowledged as net-new in §4; Phase 2 budgets an extra half-day; evaluate OpenAI-compat endpoint first to potentially skip native implementation entirely |
| `gpt-5.4-nano` or other reasoning model mistakenly assigned to dedup | Medium | Medium | Default table explicitly selects non-reasoning dedup models; docstring warns against reasoning models for this role |
| Scope creep toward v2 | High | Critical | Spec §Non-Goals is law. Roadmap exists so "good ideas" have a home without bloating v1 |

---

## 8. Explicit Non-Goals (unchanged)

Per spec §Non-Goals, the following are OUT for v1:

- IDE-native integration (gutter annotations, squigglies, extensions)
- CI/CD integration (GitHub Actions, PR bots)
- Hosted service / SaaS
- Changes to dvad core
- Automatic reference file discovery / repo crawling
- Custom rubrics via MCP
- Multi-turn review sessions
- Structured `parent_review_id` delta computation (metadata linkage only)
- Batch / multi-artifact review
- Finding location hints (`file_path`, `approx_lines`)
- Anything on `roadmap.md` v2/v3 lists

---

## 9. Success Criteria

1. Two-command install works for a developer with ≥2 provider keys (or one key that provides ≥2 distinct models)
2. Agent-invoked `dvad_review` returns structured findings in <30s p50 for a <5K-token artifact
3. The handoff with adversarial trail is visibly better than without — to the point where "done, tests pass" feels reckless by comparison
4. A contributor can read the codebase in one sitting and hold the architecture in their head
5. Meta-success: a dvad review of this plan produces findings that improve it

---

## 10. Decisions Made in v2 (with Rationale)

Explicit record of the five judgment calls made between pairings 1/2 and pairings 3/4. Each is a real design decision, not a reviewer catch. Pairings 3/4 may attack them — the rationale is here so the attack is informed.

### 10.1 Drop the 30-minute-read stopwatch

**Decision:** Replaced Guiding Constraint #1's "read in under 30 minutes / 700–900 LoC" with "small, focused, readable in one sitting / ~1,200–1,500 LoC as a sanity check, not a cap."

**Rationale:** The stopwatch was synthetic. Reading speed varies 2–3x across developers; attention varies more (ADHD is common in the population). 40 minutes vs 30 is a rounding error; the actual discipline is "don't add a module without a reason." The honest LoC landing spot, after folding in reviewer-driven additions (path validation, discriminated union, structured output enforcement, budget persistence), is ~1,200–1,500. That's the number we commit to. The real goal — the repo feels small and inviting when a developer clones it — is served by that range.

### 10.2 `outcome` and `degraded` are two independent fields

**Decision:** `outcome` is content severity only (`clean | caution | critical_found`). `degraded` is a separate boolean on the `ok` response. An agent parsing the response always sees both signals.

**Rationale:** Pairing 1 proposed a single-field priority ordering (`critical_found > degraded > caution > clean`); pairing 2 proposed splitting. Single-field loses information: a review with critical findings AND a failed provider would surface as `critical_found`, hiding the coverage problem. Agents making downstream decisions need both signals independently. The cost of two fields is one extra boolean in the schema; the benefit is signal preservation.

### 10.3 Budget: disk-persisted, calendar day in local time, no override

**Decision:** Daily spend persisted to `~/.local/share/devils-advocate/budget/YYYY-MM-DD.json` with `fcntl.flock`, local timezone, midnight rollover, no timezone override. `DVAD_BUDGET_DAILY=0` disables the cap entirely.

**Rationale:** A "24-hour sliding window" is computer-brain, not human-brain; humans mean calendar day when they say "daily." Disk persistence isn't a feature creep — it's the minimum bookkeeping to make the "daily" label honest, using the same directory the spec already endorses for review persistence. File locking handles the rare multi-MCP-server concurrency case at ~10 LoC. Timezone overrides add configuration fatigue we don't need in v1. Elite users who don't want any cap set `DVAD_BUDGET_DAILY=0` — one env var, no yaml required.

### 10.4 Budget warning thresholds surfaced in-response, not as prompts

**Decision:** `budget_status.warning_level` in every response: `soft` at ≥70% of cap, `hard` at ≥85%. The skill tells the agent to include a one-liner in its handoff when `warning_level != "none"`. No user interaction required; no permission prompt.

**Rationale:** Mirrors the pattern of Claude Code's context-remaining indicators — subtle, inline, non-interruptive. Elite users who don't set caps see nothing; users with caps see escalating inline warnings that let them act on their own timing. Adding warnings to the response shape is a few bytes; adding interactive prompts would break the "silent infrastructure" UX promise for agent-invoked reviews.

### 10.5 Model-based dedup primary, non-reasoning models, pipelined from 2/3-complete; deterministic as fallback

**Decision:** Dedup defaults to a fast **non-reasoning** model per provider (haiku / gpt-4o-mini / gemini-2.5-flash). Dedup call fires when 2/3 reviewers have completed, overlapping with the tail reviewer. Deterministic grouping stays as the spec §10 fallback chain (cheapest reviewer model → deterministic grouping).

**Rationale:** Consensus counts are load-bearing — the spec's "filter on severity + consensus" pitch to agents depends on accurate grouping. Deterministic-only would have degraded consensus accuracy meaningfully (70–85% vs 95–99% for model-based). The fix for the latency concern isn't to drop model-based dedup; it's to (a) use non-reasoning models for the role (`gpt-5.4-nano` is reasoning, which is why dvad core reviews were seeing 5–15s dedup calls), and (b) pipeline from 2/3-complete so dedup overlaps with the tail reviewer's wall-clock. Net dedup latency: ~0–2s non-overlapped instead of 5–15s.

---

## 11. Prior Review Dispositions

Across pairings 1 (GPT-5.4 + GLM-5.1) and 2 (Claude-Opus-4.6 + Gemini-3.1-pro-preview). 43 findings total.

### Accepted and folded into v2 (36 items)

Every one of these is now reflected in the plan above.

- Three-tier JSON parsing (native mode → strip fences → ReviewerError with raw_response)
- `call_openai_responses` added to Phase 2 (gpt-5 uses /v1/responses)
- `call_google` reclassified as net-new code (not a port); evaluate OpenAI-compat endpoint first
- Discriminated `ToolResponse` union with all status variants
- Path validation for `reference_files` (realpath, repo_root containment, symlink escape rejection, size caps)
- `reference_files` flow fully defined: read, secrets-scan, concatenate with delimiters, include in cost/context preflight
- Secrets scanner operates on strings (`scan(content: str)`), CLI wraps for file input
- Secrets scan covers full outbound payload (artifact + instructions + reference_file contents) before each external call
- `DVAD_SECRETS_MODE` env override for zero-config escape hatch
- Context-window preflight for reviewers AND dedup; `oversize_input` status
- Overall `review_deadline` with fan-out and dedup sub-budgets; cancellation → ReviewerError; partial-results rule applied
- `asyncio.as_completed` instead of `gather` (incompatible with per-reviewer progress signals)
- Dedup merge rules: severity = max, category = modal + highest-severity tie-break
- Category normalization via static mapping table (~20 entries) in types.py
- Deterministic dedup algorithm precisely specified (tokenizer, thresholds, category-aware grouping, text normalization)
- `minimum_met` = ≥2 distinct reviewer models (same provider OK with `diversity_warning`)
- `diversity_warning` surfaced in all three tool responses
- `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` support for proxy users
- Low-cost non-reasoning dedup defaults per provider (haiku / gpt-4o-mini / gemini-2.5-flash)
- Budget TOCTOU → `asyncio.Lock` + `fcntl.flock`
- Budget persistence, calendar day, local time rollover
- Budget warning thresholds (70% / 85%) surfaced in response
- `DVAD_BUDGET_DAILY=0` disables cap
- Ability to explicitly disable Anthropic thinking (not just strip the budget logic)
- Persistence opt-in, metadata-only default, 0600 files, redaction mapping never persisted, `original_artifact_sha256` + `redacted_locations` in response for manual cross-reference
- Pipelined dedup (start at 2/3 reviewers complete)
- Model validation via `probe` command (not an automatic hot-path check)
- Logging: stdlib `dvad_agent` namespace, stderr only, never stdout (MCP stdio hazard)
- `httpx.AsyncClient` lifecycle: single instance at server startup, shared, closed on shutdown with drain period
- `dvad-agent install` bootstrap command writes MCP config + copies skill, with paste fallback on any step failure
- `test_output.py`, `test_cost.py`, `test_budget.py` added
- JSON-schema contract tests for every ToolResponse status variant
- Category enum clarified: exactly 9 values including `other` (not "9 + other")
- Reviewer output capped (hard token cap prevents rambling, protects latency budget)
- `secrets_handling` default `abort`, configured at config layer, not per-call (prompt-downgrade protection)
- `degraded` never masks content severity (two-field design per §10.2)

### Rejected in v2 — do not re-raise without new information

Pairings 3/4: these were considered and deliberately declined. If you have new evidence or a failure mode we didn't consider, raise it; otherwise, move on.

- **Disk-persisted redaction mappings.** Security risk (mapping is a secret); the `original_artifact_sha256` + `redacted_locations` approach achieves the "human can resolve placeholders" goal without persisting the secret itself.
- **Per-call `secrets_handling` parameter in `dvad_review`.** An LLM-driven caller could downgrade the security control from a prompt. Config-layer + env var only.
- **Automatic reference-file discovery / repo crawling.** Explicitly spec §Non-Goals. Agent passes `reference_files`; dvad does not infer.
- **Model-based dedup skipped entirely ("always deterministic").** Would break consensus accuracy. Consensus is load-bearing; see §10.5.
- **24-hour sliding-window budget.** Not what humans mean by "daily"; see §10.3.
- **Single-field outcome with `degraded` as a precedence tier.** Masks signal; see §10.2.
- **Timezone override for budget rollover (UTC vs local).** Configuration fatigue; local-only is the default and there's no override.
- **Embedding-based semantic similarity in the deterministic dedup fallback.** Adds 100MB+ dependency; violates the "no deps beyond httpx/mcp/pyyaml" constraint; deterministic fallback is already explicitly lower quality.
- **Prompt injection pre-scan.** Already rejected in spec.v3 (multi-model adversarial design is itself the defense; regex would false-positive and is trivially bypassed).
- **Dedup on raw unparsed reviewer output.** Dedup prompt requires structured fields (SEVERITY / CATEGORY / DESCRIPTION) that only exist post-parse.
- **Interactive budget-approval prompts.** Breaks the "silent infrastructure" UX for agent-invoked reviews; inline response-level warnings at 70%/85% are the v1 surface.

### Escalated and resolved

The 7 escalated items from both pairings (LoC reconciliation, dedup fallback, CLI size, reference_files flow, outcome derivation ambiguity, budget window, model validation) are now resolved via the decisions in §10 and the accepted items above.

---

## 12. Next Steps

1. Run this plan (v2) through dvad using the command at the top. Different model pairings than 1 and 2.
2. Fold any new findings into plan.v3 if warranted; if pairings 3/4 find only refinements, move to Phase 0.
3. Phase 0 → Phase 10 per §3. Each phase's success check is the gate.
4. Phase 10a demo recorded; Phase 10b handed to the v2 collaborator.
5. Ship when Phase 10 passes.

---

*Plan v2. Supersedes v1. Ready for adversarial review.*
