# dvad-agent-native v1 — Implementation Plan (v3)

**Status:** Revised after four rounds of adversarial review — pairings 1 (GPT-5.4 + GLM-5.1), 2 (Claude-Opus-4.6 + Gemini-3.1-pro-preview), 3 (MiniMax-M2.7 + Kimi-K2.5), 4 (Claude-Opus-4.6 + GLM-5.1, attacking plan.v2). 86 findings across 4 rounds; 11 decisions explicitly made with rationale; spec deviations consolidated.
**Date:** 2026-04-23
**Spec reference:** `docs/spec.v3.md` — with explicit deviations documented in §10.6
**Supersedes:** `docs/plan.v1.md`, `docs/plan.v2.md`

---

## dvad Review Command

```bash
/media/kelleyb/DATA2/code/tools/devils-advocate/.venv/bin/dvad review \
  --mode plan --project dvad-v1-agent-native \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/plan.v3.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/docs/spec.v3.md \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/providers.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/config.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/dedup.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/output.py \
  --input /media/kelleyb/DATA2/code/tools/devils-advocate/src/devils_advocate/prompts.py
```

---

## 1. Guiding Constraints

1. **Small, focused, readable in one sitting.** A skilled Python developer should be able to hold the architecture in their head after a single reading. No module added without a clear reason. No abstraction introduced ahead of a second concrete use case. Expected landing: ~1,200–1,500 LoC of production Python excluding tests — as a sanity check, not a cap. Exceeding it is a signal to ask "what's paying for these lines?" not a trigger to refuse work the reviewers proved was necessary. The CLI module (`cli.py`) is explicitly unbounded in size — if phase-gate testing earns its keep, it grows to fit.
2. **Standalone.** No import dependency on dvad core. Port patterns; do not wrap.
3. **Lite mode only.** No governance, no author response, no revision, no rebuttals. Full-mode depth lives in dvad core; a bridge is a future question.
4. **Stateless review pipeline, bookkeeping exception for budget.** Each `dvad_review` call is a pure function of its inputs with respect to artifact analysis. Budget and audit persistence are separate — they write always, and budget enforcement reads daily spend as a policy gate. This carve-out is documented here rather than pretended away.
5. **Zero-config with respectful overrides.** Works with just API keys in env — including proxy base URLs for developers using OpenRouter, Groq, or local models. `models.yaml` is an override path, never a prerequisite.
6. **Advisory, not gate.** Every outcome — including `critical_found` — is information, not a stop signal. Word choice in error messages, outcomes, and logs reflects this.
7. **Secrets never leave without consent.** Pre-scan is a hard gate before any external API call. Scans cover each distinct outbound payload type once: the shared reviewer payload before fan-out, and the dedup payload before the dedup call. No exceptions for performance.
8. **Platform support: Linux and macOS; Windows via WSL.** Native Windows support is deferred to v2. The v1 codebase uses `fcntl`, POSIX file permissions, and XDG paths; claiming first-class Windows support on top of a POSIX-shaped foundation would be misleading. WSL covers the overwhelming majority of Windows-based developers installing Python MCP servers from `pipx` in 2026. Native Windows (~50 LoC of platform abstraction + CI matrix + testing) is planned for v2 alongside the IDE-native push.

---

## 2. Architecture at a Glance

```
devils-advocate-agent-native/
├── pyproject.toml                  (pipx-installable, entry points for CLI + MCP server)
├── README.md                       (install line, one demo, link to spec, platform note)
├── LICENSE                         (MIT)
├── docs/
│   ├── spec.v3.md                  (frozen product definition + deviations noted here)
│   ├── plan.v3.md                  (this file)
│   ├── roadmap.md                  (v2/v3/rejected)
│   └── conversation.01.md          (strategic origin, for future context)
├── src/dvad_agent/
│   ├── __init__.py
│   ├── __main__.py                 (python -m dvad_agent → CLI)
│   ├── types.py                    (dataclasses incl. ReviewContext, Finding,
│   │                                ReviewResult, ModelConfig, ToolResponse
│   │                                discriminated union, CATEGORY_NORMALIZATION_TABLE)
│   ├── config.py                   (key + base-URL detection, default model table,
│   │                                diversity-warning logic, logging setup with
│   │                                API-key redaction filter)
│   ├── budget.py                   (daily spend: asyncio.Lock + fcntl.flock via
│   │                                asyncio.to_thread; calendar-day local-time
│   │                                rollover; corrupted→fail-closed, missing→init;
│   │                                70/85% thresholds; umask 0o077 at startup)
│   ├── cost.py                     (token estimation, pricing table with
│   │                                "unavailable" fallback for unknown models,
│   │                                context-window preflight)
│   ├── providers.py                (httpx: call_anthropic, call_openai_compatible,
│   │                                call_openai_responses, call_google (or reuse
│   │                                call_openai_compatible per §3 Phase 2),
│   │                                call_with_retry, explicit max_output_tokens
│   │                                threading, thinking_enabled handling)
│   ├── secrets.py                  (scan(content: str) → list[SecretMatch],
│   │                                abort/redact/skip modes, DVAD_SECRETS_MODE env)
│   ├── prompts.py                  (rubric per artifact_type, dedup prompt)
│   ├── review.py                   (lite-mode orchestrator: repo_root validation,
│   │                                reference_files handling, as_completed fan-out,
│   │                                fan-out sub-budget cutoff, post-fan-out dedup
│   │                                on final reviewer set, deadline enforcement,
│   │                                degraded derivation relative to pre-failure
│   │                                state, slow-review warning at 20s, schema-
│   │                                validate reviewer outputs)
│   ├── dedup.py                    (model-based primary using non-reasoning
│   │                                defaults, deterministic fallback with Jaccard
│   │                                ≥0.7 + bigram check)
│   ├── output.py                   (markdown renderer including deterministic-
│   │                                fallback caveat when dedup_method="deterministic";
│   │                                JSON shaping)
│   ├── server.py                   (MCP stdio server: 3 tools, progress via
│   │                                as_completed, httpx lifespan with explicit
│   │                                shutdown sequence, broken-pipe cancellation,
│   │                                startup-failure stderr + non-zero exit)
│   └── cli.py                      (developer testing surface — unbounded size,
│                                    phase-gate subcommands)
├── skill/
│   └── dvad.md                     (Claude Code skill definition)
├── scripts/
│   └── install.py                  (dvad-agent install bootstrap — writes MCP
│                                    config, copies skill, with paste fallback)
└── tests/
    ├── test_secrets.py
    ├── test_config.py
    ├── test_budget.py              (rollover, threshold warnings, locking, fail-
    │                                closed on corruption, init on missing)
    ├── test_cost.py                (pricing table, context-window checks,
    │                                unavailable-pricing warning path)
    ├── test_review.py              (partial failure paths, outcome+degraded
    │                                relative semantics, deadline enforcement,
    │                                reference file flow, slow-review warning)
    ├── test_dedup.py               (Jaccard 0.7 + bigram rule deterministic;
    │                                model path mocked)
    ├── test_prompts.py
    ├── test_output.py              (markdown structure, dedup caveat when
    │                                deterministic, redaction placeholders)
    ├── test_server.py              (MCP tool schemas per ToolResponse variant,
    │                                contract tests against JSON-schema fixtures,
    │                                broken-pipe cancellation, startup failure)
    ├── test_paths.py               (repo_root canonicalization, size caps,
    │                                traversal/symlink/absolute rejection)
    └── test_install.py             (fresh settings.json write, merge into existing,
                                     backup creation, --dry-run output, paste
                                     fallback on write failure)
```

**Why Python:** dvad core is Python; provider patterns port cleanly; MCP has a first-party Python SDK (`mcp` package); pipx is the cleanest single-command install path.

**Why httpx direct (not provider SDKs):** no SDK version lock-in, tiny dependency footprint, async-native, provider API changes surface as HTTP errors instead of SDK exceptions.

**Why a separate CLI:** for phase-gate verification during the build and ongoing developer debugging. The CLI is development infrastructure, not a product surface. It is never the thing we optimize for adoption or polish; it's the tool that lets us verify each phase before wiring it into MCP.

**Why no Windows-native code paths in v1:** every file-I/O change would need to be re-verified on Windows, and the user demographic for an agentic-AI MCP server skews Mac/Linux/WSL already. WSL gives Windows users first-class compatibility through a POSIX shim they likely already have. Native Windows is planned for v2 alongside IDE-native work; see §8 Non-Goals and §10.6.

---

## 3. Work Breakdown

Phases are ordered so each one produces a testable deliverable. Do not start phase N+1 until phase N runs clean.

### Phase 0 — Scaffolding

**Deliverable:** Empty-but-installable package. `pipx install -e .` works; `dvad-agent --help` prints; `dvad-agent-mcp` starts and exits cleanly on EOF.

- `pyproject.toml` with `project.scripts` entries for CLI (`dvad-agent`), MCP server (`dvad-agent-mcp`), and install bootstrap (`dvad-agent install` as a subcommand)
- Dependencies: `httpx`, `mcp`, `pyyaml`. No SDKs, no embedding libraries, no database, no `filelock` (we have `fcntl` on POSIX).
- Package skeleton: every module listed above exists with a docstring and maybe a `pass`
- `README.md` stub with install line, platform note (Linux/macOS/WSL), "coming soon" demo placeholder
- `LICENSE` (MIT)
- `.gitignore`, `.editorconfig`, pre-commit with `ruff` + `black`

**Success check:** `pipx install -e .` resolves and both entry points execute.

### Phase 1 — Types, Config, Logging, Budget Scaffolding

**Deliverable:** `dvad-agent config` prints a JSON blob describing what's available; `dvad-agent budget` shows current day's spend; logs go to stderr; `os.umask(0o077)` is set at startup.

**Types (`types.py`):**

- `ModelConfig` — provider, model_id, api_key, api_base, cost_per_1k_input (Optional), cost_per_1k_output (Optional), context_window, use_responses_api (bool — OpenAI /v1/responses dispatch), use_openai_compat (bool — transport hint independent of provider identity), thinking_enabled (bool, default **False** — positive naming, reviewers default to disabled; dedup always False), max_output_tokens (int — role-specific cap, default 1500 for reviewer, 2000 for dedup)
- `ProviderKey` — provider name, api_key, optional api_base
- `Severity` — enum: critical, high, medium, low, info
- `Category` — closed enum, 9 values total including `other`: correctness, security, performance, reliability, testing, maintainability, compatibility, documentation, other
- `Outcome` — enum (content severity ONLY; deliberately does NOT include `degraded` — see §10.2 and §10.6 Spec Deviations): `clean`, `caution`, `critical_found`
- `Finding` — severity, consensus, category, category_detail, issue, detail, models_reporting
- `ReviewerError` — model_name, provider, error_type (`timeout` | `deadline_exceeded` | `rate_limit` | `server_error` | `parse_failure` | `schema_invalid` | `connection_error`), message, raw_response (preserved for parse/schema failures)
- `SecretMatch` — pattern_type, approx_line_range, channel (`artifact` | `instructions` | `reference_file:<path>`)
- `BudgetStatus` — spent_usd, cap_usd, remaining_usd, warning_level (`none` | `soft` | `hard`), day (YYYY-MM-DD string)
- `ReviewContext` — **dataclass matching the spec's `context` parameter**: project_name (Optional), repo_root (Optional), reference_files (Optional list of paths), instructions (Optional). Constructed by `server.py` from MCP tool payload before handing off to `review.py`.
- `ReviewResult` — review_id, parent_review_id, artifact_type, mode, outcome (Outcome), degraded (bool — independent of outcome), diversity_warning (bool), models_used, duration_seconds, cost_usd, findings, summary, reviewer_errors, dedup_method (`model` | `deterministic`), dedup_skipped (bool), redacted_locations (list of `SecretMatch` shape without actual values), original_artifact_sha256, budget_status (BudgetStatus), report_markdown
- `ToolResponse` — **discriminated union with required `status` field**. Every MCP tool return carries this shape:
  - `ok` — review completed, full `ReviewResult` in body
  - `setup_required` — no keys detected; includes setup_steps and docs_url
  - `skipped_budget` — daily cap hit; includes BudgetStatus
  - `skipped_secrets` — secrets detected in abort mode; includes matches (pattern type + location only)
  - `oversize_input` — artifact + context exceeds model context window; includes per-model fit details
  - `failed_review` — <2 reviewers succeeded; includes reviewer_errors
  - `invalid_request` — e.g., `reference_files` supplied without `repo_root`; includes structured reason
  - `degraded` — **NOT a status.** Always a flag on an `ok` response.
- `CATEGORY_NORMALIZATION_TABLE` — static dict (~20 entries) in code, hardcoded and versioned with the package. Deterministic normalization is part of the tool contract; user-editable tables break reproducibility across environments. Extension policy: add entries based on observed model outputs; reserve externalization for v2 with an explicit override contract.

**Config (`config.py`):**

- Env-key detection: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` / `GEMINI_API_KEY`
- **Base URL detection:** `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL` — if present, propagated into `ModelConfig.api_base`
- **Default model table (revised — two reviewer-role models per provider):**
  - Anthropic: `claude-sonnet-4-6` (reviewer), `claude-opus-4-7` (reviewer), `claude-haiku-4-5-20251001` (dedup, non-reasoning, `thinking_enabled=False`)
  - OpenAI: `gpt-5` (reviewer, `use_responses_api=True`), `o3` (reviewer, `use_responses_api=True`), `gpt-4o-mini` (dedup, non-reasoning)
  - Google: `gemini-2.5-pro` (reviewer), `gemini-2.5-flash` (reviewer AND dedup — non-reasoning, fast)
- **`minimum_met` logic:** true when ≥2 distinct reviewer-role models are available, even from the same provider. With a single Anthropic key, sonnet + opus satisfy the minimum; diversity_warning fires because they share a provider.
- `diversity_warning` surfaced in all three tool responses whenever all reviewers share a provider
- `models.yaml` override precedence: project-local → `$DVAD_HOME` → XDG
- Budget defaults: `$2.00/review`, `$50.00/day`; override via `DVAD_BUDGET_PER_REVIEW` / `DVAD_BUDGET_DAILY`; `DVAD_BUDGET_DAILY=0` disables the daily cap entirely
- Secrets handling: single authoritative `secrets_handling` field, default `abort`, override via `DVAD_SECRETS_MODE` env var (`abort` | `redact` | `skip`); **exposed in `dvad_config` response as part of the public contract**
- **Logging setup:** stdlib `logging` under `dvad_agent` namespace; `StreamHandler(sys.stderr)` only; default INFO; DEBUG under `DVAD_LOG_LEVEL=debug`. Root logger explicitly reconfigured at server startup to prevent stdout output (would corrupt MCP stdio transport).
- **Log redaction filter:** custom `logging.Filter` that scrubs `Authorization`, `x-api-key`, `x-goog-api-key` headers and any plausible API key patterns from log records before emission. Applied to the `dvad_agent` logger and to httpx's logger if it's imported.

**Cost (`cost.py`):**

- Token estimator (4 chars per token heuristic, ported unchanged from dvad core)
- `estimate_cost(model, in_tokens, out_tokens) -> float | None` — returns `None` when pricing data is unavailable
- **Unknown-model pricing:** when a user-configured model has no cost metadata, `estimate_cost` returns `None` and the orchestrator surfaces a `pricing_unavailable: true` warning in `dvad_estimate` / `dvad_config` / `ReviewResult`. **Never invent a conservative default** — would falsely block legitimate proxy-routed or local-model work. Budget preflight treats `None` as "unknown, proceed without preflight block" and logs a warning.
- `check_context_window(model, text) -> (fits: bool, est_tokens: int, limit: int)` — ported from dvad core

**Budget (`budget.py`):**

- Daily spend persisted to `~/.local/share/devils-advocate/budget/YYYY-MM-DD.json` (file mode 0600, directory 0700)
- **Calendar day in local timezone.** Midnight local-time rollover. No timezone override.
- **Two-layer locking:** `asyncio.Lock` (in-process, for coroutine safety within a single MCP server) PLUS `fcntl.flock` via `asyncio.to_thread()` (cross-process, for multiple MCP servers against the same file). The async lock is acquired first; the file lock is acquired inside the executor so the event loop is never blocked.
- **Warning thresholds:** `warning_level` is `soft` at ≥70% of cap, `hard` at ≥85%. **Slow-review warning fires at 20s wall-clock** for the review orchestrator (not a budget concern, but a UX guardrail — terminal silence past 20s feels dead). Both mirror Claude Code's inline indicators — subtle, response-embedded, no prompt interruption.
- **Corrupted-file handling:** if today's budget file exists but fails JSON parse or schema check, budget enforcement **fails closed** — review returns `skipped_budget` with an explanatory message, does not proceed. A corrupted file may indicate tampering or disk error; refusing to proceed prevents unaccounted spend.
- **Missing-file handling:** absence of today's file is the normal first-run or post-midnight state. Initialize to $0, proceed with the review, write the file after.
- **Disk full on write:** log, proceed with the review. Bookkeeping hiccup does not block user work — this is the one case where we accept a small accounting gap rather than refuse a review the user already authorized via their cap.
- `DVAD_BUDGET_DAILY=0` disables the cap but continues tracking spend (response still carries BudgetStatus)
- **Directory hardening:** `os.umask(0o077)` set at MCP server and CLI startup. `os.makedirs(..., mode=0o700)` with explicit mode. On existing-directory detection, check permissions; log a warning if more permissive than 0700 and attempt `os.chmod` to tighten.
- CLI: `dvad-agent budget` prints today's BudgetStatus

**Success check:** With only `ANTHROPIC_API_KEY` set, `dvad-agent config` reports 1 provider, `minimum_met: true` (sonnet + opus satisfy it), `diversity_warning: true`. With two provider keys, `diversity_warning: false`. With `OPENAI_BASE_URL` + `OPENAI_API_KEY`, OpenAI provider uses the custom base. `dvad-agent budget` shows today's file exists with mode 0600. Corrupting the budget file and running a review returns `skipped_budget`. Log output has no `x-api-key` values visible at DEBUG level.

### Phase 2 — Provider Layer

**Deliverable:** `dvad-agent probe --model <name>` returns a short response and usage dict for any model in the default table, for each provider.

**Provider functions (`providers.py`):**

- `call_anthropic(client, model, system, user, max_output_tokens) -> (text, usage)` — httpx to `/v1/messages`; explicitly sets `thinking: {"type": "disabled"}` when `model.thinking_enabled is False` (v1 default for reviewer roles); tool-use structured-output enforcement for JSON; enforces `max_tokens=model.max_output_tokens`.
- `call_openai_compatible(client, model, system, user, max_output_tokens) -> (text, usage)` — httpx to `{api_base or default}/chat/completions`; `response_format: {type: "json_object"}` when JSON requested; enforces `max_tokens=model.max_output_tokens`.
- `call_openai_responses(client, model, system, user, max_output_tokens) -> (text, usage)` — httpx to `{api_base}/responses`, required for gpt-5 and o3 (reasoning series); enforces `max_output_tokens` per Responses API shape.
- `call_google(client, model, system, user, max_output_tokens) -> (text, usage)` — **net-new code** if the OpenAI-compatible endpoint evaluation (below) fails. Targets AI Studio Gemini API v1beta (`generateContent`), `x-goog-api-key` header, `contents[].parts[]`, `responseMimeType: "application/json"`, `max_output_tokens` via `generationConfig.maxOutputTokens`. Vertex AI / OAuth deferred.
- `call_with_retry(...)` — exponential backoff with jitter, 529-specific budget (up to ~30s), ported from dvad core. **This retry budget is load-bearing** in the decision to hold the 45s overall deadline (§10.7).
- **Dispatcher `call_model(model, system, user) -> (text, usage, cost)`** routes by:
  1. If `model.use_responses_api` → `call_openai_responses`
  2. Else if `model.use_openai_compat` (set for Google-via-compat-endpoint) → `call_openai_compatible` with `api_base` and Bearer auth. **Provider identity is preserved** (`model.provider="google"`) even when transport is OpenAI-compatible, so diversity/degraded computation uses the correct provider set.
  3. Else route by `model.provider` to the native function.

**Google OpenAI-compat endpoint evaluation (Phase 2 gate):**

Before writing native Gemini code, verify the compat endpoint (`generativelanguage.googleapis.com/v1beta/openai/`) against four explicit criteria. All four must pass to use compat:

1. **Structured JSON output:** `response_format: {type: "json_object"}` produces valid JSON on a test prompt
2. **Usage metadata:** response includes `prompt_tokens` and `completion_tokens` in the standard OpenAI shape for cost tracking
3. **Model IDs:** `gemini-2.5-pro` and `gemini-2.5-flash` are reachable via the compat endpoint
4. **Auth:** standard `Authorization: Bearer <GOOGLE_API_KEY>` works

If any criterion fails, fall back to native `call_google` implementation using `x-goog-api-key` header. Decision recorded in Phase 2 commit message.

**Three-tier JSON parsing strategy:**

1. Provider-native structured output where supported (Anthropic tool_use, OpenAI `response_format`, Google `responseMimeType` or compat `response_format`)
2. If that fails or returns markdown-wrapped output, `sanitize_json_output()` strips ```json fences and extracts the first valid JSON block via regex
3. **Schema validation** after successful parse: parse JSON → validate against typed `Finding[]` schema (required fields: severity, category, issue; optional: detail). If schema validation fails, treat as `ReviewerError` with `error_type: "schema_invalid"` and `raw_response` preserved. Malformed-but-syntactically-valid JSON never enters the pipeline.
4. If all tiers fail, `ReviewerError` with `error_type: "parse_failure"` and `raw_response` preserved. Counts against ≥2-success threshold.

**httpx.AsyncClient lifecycle:**

- MCP path: single client created at server startup via MCP SDK's lifespan hook (or contextmanager wrapper fallback), stored on server state, shared across reviews.
- **Shutdown sequence (explicit, not magical):**
  1. Stop accepting new MCP tool calls
  2. Collect in-flight review task references from server state
  3. `await asyncio.wait(tasks, timeout=10)` — tracked task set, bounded drain
  4. Cancel remaining tasks; log partial-cost telemetry for cancelled reviews
  5. `await client.aclose()` — close httpx client
  6. Release budget file locks cleanly
- **Broken-pipe handling:** detect `BrokenPipeError` / EOF on stdio during an in-flight review. Cancel the review task, log partial cost; the client can never receive the result, so continuing to spend API money is pure waste.
- **Startup failure handling:** if the MCP server cannot create the budget directory, cannot open the XDG path, or hits a logging configuration error at startup, it writes a **human-readable error to stderr** (not stdout, which is the MCP transport) and exits with a non-zero code. MCP clients that see a non-zero exit should surface the stderr message; clients that only see EOF at least get a broken-server signal.
- CLI path: client created per invocation inside `async with httpx.AsyncClient() as client:` — no lifecycle drama.

**Success check:** `probe --model claude-sonnet-4-6` works with thinking explicitly disabled, `--model gpt-5` dispatches to Responses endpoint, `--model gemini-2.5-pro` uses whichever path the Phase 2 gate selected. Log output at DEBUG shows no API key values. Sending SIGTERM mid-probe triggers clean shutdown with drain period.

### Phase 3 — Secrets Pre-Scan

**Deliverable:** `scan(content: str) -> list[SecretMatch]` works on arbitrary strings; `dvad-agent scan --file path/to/artifact.md` is a convenience wrapper that reads and calls `scan()`.

- **String-based scanner.** Core function signature: `scan(content: str, channel: str) -> list[SecretMatch]`. The `channel` label (`artifact` | `instructions` | `reference_file:<path>`) is attached to each match for precise response reporting.
- Pattern set: AWS keys (`AKIA[0-9A-Z]{16}`), `BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY`, Stripe live keys, GitHub PATs, Slack tokens, generic `KEY=high-entropy-value` heuristic, connection strings with embedded passwords
- File-path reference heuristics: mentions of `.env`, `credentials.json`, `secrets.yaml`, key vault paths
- Entropy gate on `KEY=VALUE` lines to suppress template placeholders and test fixtures
- **Three modes:** `abort` (default), `redact`, `skip`. `skip` is only selectable via `DVAD_SECRETS_MODE=skip` env var; never a per-call tool parameter (security control must not be prompt-downgradable by an LLM-driven caller).
- `redact` replaces matches with stable placeholders (`[REDACTED_1]`, `[REDACTED_2]`), mapping held in memory only. Response includes `redacted_locations` (channel + pattern type + line range, never the secret values) and `original_artifact_sha256` for manual cross-reference.
- **Per-outbound-payload scanning (not per-HTTP-call, not once-per-review):**
  - Before fan-out: assemble the shared reviewer payload (artifact + instructions + concatenated reference-file contents with delimiters). Scan once. Abort or redact.
  - Before dedup: assemble the dedup payload (concatenated reviewer findings). Scan separately. Rationale: reviewer outputs can echo user content that might contain a secret the first scan missed, especially under `DVAD_SECRETS_MODE=skip`. Guiding Constraint #7 applies to bytes leaving the machine, not just direct user input.

**Success check:** Secrets planted in each channel (artifact, instructions, reference_file) are each caught and labeled with their channel. Dedup-payload scan detects secrets echoed by a reviewer. False-positive artifact (test fixtures documenting secret patterns at low entropy) doesn't trip. `DVAD_SECRETS_MODE=redact` converts an abort response to a redact response without any config file edits.

### Phase 4 — Lite-Mode Review Orchestrator

**Deliverable:** `dvad-agent review --artifact-type plan --file plan.md` returns a `ToolResponse` JSON with status and full `ReviewResult` in the `ok` case, or an explicit non-`ok` variant.

**Pipeline in `review.py`:**

```python
async def run_lite_review(
    artifact: str,
    artifact_type: str,
    context: ReviewContext,
    budget_limit: float | None,
    parent_review_id: str | None,
    deadline_seconds: float = 45.0,
    slow_warning_seconds: float = 20.0,
) -> ToolResponse: ...
```

1. **Validate `repo_root` (if context.reference_files non-empty):**
   - Must be non-empty string
   - `realpath(repo_root)` must exist and be a directory
   - Must not be `/`, must not be empty after resolution
   - Must fall under a sane base (user's home dir or CWD — enforced policy documented in config)
   - **If `reference_files` is non-empty but `repo_root` is missing or fails validation:** return `ToolResponse{status: "invalid_request", reason: "reference_files requires a valid repo_root"}`. This is a documented spec deviation (§10.6).
2. **Load reference files (if any):**
   - Each path must resolve (after `realpath` / symlink resolution) under the validated `repo_root`
   - Reject absolute paths, `..` traversal, symlink escapes
   - **Size caps: 1 MiB per individual file, 5 MiB total across all reference files.** Rejected paths surface as structured warnings in the response; do not silently drop.
3. **Assemble reviewer outbound payload:** artifact + instructions + concatenated reference-file contents with `=== REFERENCE FILE: {path} ===` delimiters.
4. **Secrets pre-scan (payload 1):** scan the full reviewer payload once. Abort (→ `skipped_secrets`) or redact per mode.
5. **Context-window preflight:** compute token fit per reviewer model and per dedup model prompt. **No silent truncation.** If any reviewer prompt exceeds its model's window, return `ToolResponse{status: "oversize_input", per_model_fit: {...}}` and let the caller decide what to trim.
6. **Budget preflight:**
   - Acquire in-process `asyncio.Lock`
   - Run `fcntl.flock` check via `asyncio.to_thread`
   - Read today's budget file (fail-closed on corruption, init on missing)
   - Compare cumulative + this review's estimate (if known) against per-review cap AND daily remaining
   - If over: return `ToolResponse{status: "skipped_budget", budget_status: ...}`
   - If unknown pricing (`None` from `estimate_cost`): proceed, surface `pricing_unavailable: true` in response
7. **Build rubric prompt** for `artifact_type` (`prompts.py`).
8. **Fan out reviewers via `asyncio.as_completed`** (not `gather` — gather can't emit per-completion progress signals). Pass each reviewer their configured `max_output_tokens` (default 1500 for reviewer role). Emit MCP progress notification as each reviewer resolves.
9. **Slow-review warning:** if 20s have elapsed since fan-out began and fewer than all reviewers have completed, emit a progress notification (`status: "slow_review"`, `elapsed_seconds: 20`, `pending_reviewers: [...]`) so the agent can surface the delay in its handoff.
10. **Fan-out sub-budget cutoff (~25s):** at the fan-out phase's hard cap, cancel any still-pending reviewer tasks. Cancelled tasks become `ReviewerError` with `error_type: "deadline_exceeded"`.
11. **Apply partial-failure rule:** ≥2 reviewers must succeed (schema-valid output). If not, return `ToolResponse{status: "failed_review", reviewer_errors: [...]}`. Parse and schema failures count as failures against this threshold.
12. **Post-fan-out dedup, ONCE, on the final successful reviewer set.** No merge-in-flight — HTTP requests cannot be mutated after dispatch. If all 3 completed: dedup 3. If fan-out cutoff left 2: dedup 2. Dedup has its own sub-budget (~10s); on dedup timeout, fall through to the spec §10 fallback chain (see Phase 5).
13. **Secrets pre-scan (payload 2):** before issuing the dedup call, scan the dedup payload (concatenated findings).
14. **Normalize categories** through `CATEGORY_NORMALIZATION_TABLE` before applying dedup-derived consensus.
15. **Severity & category merge rules:**
    - Merged severity = max across contributing findings (any `critical` wins)
    - Merged category = modal across contributors; ties broken by highest-severity contributor's category
    - `consensus` = count of distinct reviewer models reporting
    - `models_reporting` preserved verbatim
16. **Derive `outcome` (content severity only, 3-value enum):**
    - Any `critical` finding → `outcome: "critical_found"`
    - Any `high` finding (no critical) → `outcome: "caution"`
    - Otherwise → `outcome: "clean"`
17. **Derive `degraded` flag (coverage health, independent field, redefined relative to pre-failure state — §10.10):**
    - `degraded: true` if ≥1 reviewer failed AND a provider that was represented in the planned reviewer set before the failure is no longer represented after the failure
    - Single-provider setups never get `degraded: true` — they already carry `diversity_warning`
    - Multi-provider setups with all providers still represented (e.g., redundant reviewer within one provider failed) → `degraded: false`
    - This lets agents distinguish "we lost coverage breadth" from "we still have all perspectives"
18. **Overall deadline enforcement:** if `deadline_seconds` (default 45s) is exceeded, cancel remaining work and return partial results via the ≥2-success rule.
19. **Render `report_markdown`** (`output.py`) — includes degraded banner, diversity warning banner, BudgetStatus footer, redaction locations if applicable, and a **deterministic-dedup caveat** when `dedup_method: "deterministic"`.
20. **Assemble `ReviewResult`**, wrap in `ToolResponse{status: "ok", ...}`.
21. **Persist (opt-in):** if `DVAD_PERSIST_REVIEWS=1`, write metadata-only review to `~/.local/share/devils-advocate/reviews/{review_id}/` (0600/0700). Redaction mappings never persisted.

**Latency Budget (rewritten with explicit overlap):**

| Milestone | p50 elapsed | p95 elapsed |
|---|---|---|
| Fan-out starts | 0s | 0s |
| First reviewer completes | 8–10s | 12–15s |
| 2 of 3 reviewers complete → **dedup kicks off** | 12–14s | 18–22s |
| Third reviewer completes (if it does) | 13–16s | 20–25s |
| Slow-review warning threshold reached | *not hit at p50* | 20s (fires during p95 tail) |
| Dedup completes (overlapping with tail reviewer) | 14–18s | 23–28s |
| Markdown render + response assembly | +<1s | +<1s |
| **Total** | **~14–18s** | **~24–29s** |
| Fan-out sub-budget cutoff | — | 25s |
| Dedup sub-budget cutoff | — | 35s (10s after fan-out cutoff) |
| **Overall hard deadline** | — | **45s** |

Slack between p95 total (~28s) and hard deadline (45s) is 17 seconds. That slack is not waste — it's the buffer that absorbs 529-retry overload events (`call_with_retry` budgets up to 30s for this), which is why tightening the deadline to 35s was rejected (§10.7).

**Load-bearing assumptions** for hitting <30s p50:
- (a) `thinking_enabled=False` on Anthropic reviewers (enforced in config + provider layer)
- (b) Reviewer `max_output_tokens=1500` (explicitly threaded through `call_model`, not prompt-instructed)
- (c) Dedup model is non-reasoning (default table enforces this)
- (d) Dedup pipelined from 2/3-complete boundary (spec'd in step 12)

Any of these flipping blows the budget.

**Success check:** Plan artifact with known weakness produces ≥1 finding against two real providers. Duration <30s p50 for 5K-token plan. Outcome derives correctly. `degraded: true` only when cross-provider coverage is lost (not just same-provider-reviewer failure). BudgetStatus present. Slow-review warning fires on injected-slow-reviewer test. `oversize_input` fires on injected-oversized test rather than silently truncating.

### Phase 5 — Dedup

**Deliverable:** Three reviewers' overlapping findings collapse into a single entry with `consensus: 3`. Three distinct findings stay as three.

**Primary: model-based dedup on the final reviewer set (post-fan-out).**

- Uses the cheapest available **non-reasoning** model per provider: haiku / gpt-4o-mini / gemini-2.5-flash. Reasoning models rejected for this role (5–15s latency overhead for a pattern-matching task — see §10.5 rationale with empirical cost-to-latency mapping).
- Prompt shape ported from dvad core's `build_dedup_prompt` and `format_points_for_dedup`, simplified (no spec-mode branching).
- `max_output_tokens=2000` for dedup role (slightly higher than reviewer role; dedup output includes grouping structure).
- **Dedup runs exactly once** after fan-out closes on the final successful reviewer set. No "merge in flight" — HTTP requests cannot be mutated mid-flight.

**Fallback chain (per spec §10, with dedup sub-budget added):**

- If the designated dedup model call fails → retry on the cheapest available reviewer model
- If no model is available for dedup → deterministic grouping
- If dedup runs but exceeds its sub-budget (~10s) → cancel, fall through to deterministic

**Deterministic algorithm (precisely specified, reproducible across implementations, tightened threshold per pairings 3+4):**

1. **Category-aware grouping:** findings only compared within the same `category` bucket. Prevents cross-category false merges (e.g., "missing auth on login" in `security` vs "missing test for login" in `testing` share "login" but should never merge).
2. **Tokenize:** lowercase the `issue` field, split on `\W+` (Unicode word boundaries), drop empty tokens.
3. **Normalize:** strip a short stop-word list (a, an, the, is, in, on, of, and, or, to, for, by).
4. **Merge rule (tightened from v2):** two findings merge if EITHER
   - Unigram Jaccard similarity ≥ **0.7** (raised from 0.6 to reduce false merges on short strings like "SQL injection in login" vs "SQL injection in payment"), AND bigram Jaccard ≥ 0.3 (word-order signal — distinguishes "injection in login" bigrams from "injection in payment" bigrams)
   - OR the first 6 non-empty normalized tokens of `issue` are identical (raised from 5)
5. **Mark result:** `dedup_method: "deterministic"`, `dedup_skipped: true`. Markdown report includes a prose caveat when this flag is set.

**Success check:** Three identical findings from three reviewers → `consensus: 3, dedup_method: "model"`. Three genuinely distinct findings in the same category stay separate under both model and deterministic paths. Forced dedup-model failure triggers the spec §10 fallback chain. Deterministic algorithm is deterministic across runs (same input → same output).

### Phase 6 — Output Rendering

**Deliverable:** `report_markdown` reads like a product. JSON and markdown convey the same information.

- `output.py` renders markdown: header, summary table, BudgetStatus footer (with warning_level callout), `diversity_warning` banner if applicable, `degraded` banner if `degraded: true`, grouped findings (critical → low), reviewer-errors section if any, cost + duration footer
- **Deterministic dedup caveat:** when `dedup_method: "deterministic"`, the markdown report includes a short paragraph: *"Findings were consolidated using deterministic grouping (fallback path; the model-based dedup was unavailable or timed out). Same-category findings may have been conservatively merged or split; review individual entries before acting."*
- **Redaction handling:** when redact mode fires, the markdown includes a dedicated section listing `redacted_locations` (channel + pattern type + line range) and the `original_artifact_sha256`. Redaction mapping itself never appears.
- JSON and markdown share one source-of-truth dataclass; the renderer is the only place that differs.

**Success check:** A report pasted into a GitHub issue renders cleanly, scannable in under 10 seconds. Redacted review shows placeholder locations without leaking values. `degraded: true` review shows the banner and content severity distinctly. `dedup_method: "deterministic"` review shows the caveat paragraph.

### Phase 7 — MCP Server

**Deliverable:** Claude Code session with MCP server configured can invoke all three tools and receive properly-shaped responses for every `ToolResponse` variant.

- Official `mcp` Python SDK, stdio transport
- **All three tools return the `ToolResponse` discriminated union** with a required `status` field. Clients branch on `status`. Contract tests in §5 validate every variant against pinned JSON-schema fixtures.
- **Tool 1 — `dvad_review`:** parameters match spec §1 shape (`artifact`, `artifact_type`, `mode`, `context`, `parent_review_id`, `budget_limit`). `server.py` constructs `ReviewContext` from the flattened MCP payload and hands it to `review.run_lite_review`. Returns `ToolResponse` with `status` discriminator.
- **Tool 2 — `dvad_estimate`:** reuses config + cost + context-window preflight. No external calls.
  - **Dedup cost estimation heuristic:** since actual reviewer findings can't be known before the review runs, assume 6 findings per reviewer at ~100 tokens each → dedup input ≈ (6 × 100 × N_reviewers) tokens; dedup output ≈ 500 tokens. Apply dedup model pricing. Document this as an approximation in the response.
  - Per-model fit results included for context-window preflight.
- **Tool 3 — `dvad_config`:** returns current config state — detected providers, base URLs, available models with pricing availability, budget defaults, **`secrets_handling` mode** (part of public contract), diversity warning status, `platform` (Linux | Darwin | Windows-via-WSL).
- **Progress notifications:** emitted at each reviewer completion boundary (via `asyncio.as_completed`), dedup start/end, deadline warnings, and the 20s slow-review threshold. If the client doesn't support progress, these are no-ops.
- **Server lifecycle:** single `httpx.AsyncClient` via MCP lifespan hook. Explicit shutdown sequence per Phase 2. Broken-pipe cancellation. Startup failure → stderr + non-zero exit.

**Success check:** From Claude Code, `@dvad` shows three tools. `dvad_review` on a plan returns `status: "ok"` structured findings in <30s p50. Zero-key invocation returns `status: "setup_required"` as success-with-data, not as MCP error. Budget-exhausted invocation returns `status: "skipped_budget"`. Invalid request (reference_files without repo_root) returns `status: "invalid_request"`. Parent-process kill mid-review triggers broken-pipe cancellation.

### Phase 8 — Claude Code Skill

**Deliverable:** `skill/dvad.md` teaches the agent when/how to invoke and how to present budget + coverage signals.

- YAML frontmatter: `name: dvad`, description, trigger keywords
- Body (from spec §2):
  - **When to invoke** — post-plan, post-implementation (>50 lines changed, schema changes, new dependencies, security-adjacent code)
  - **When NOT to invoke** — typo fixes, formatting, docs-only, exploratory, budget exhausted
  - **How to call the MCP tools** — concrete examples per `ToolResponse` variant; each variant's expected agent behavior
  - **Multi-agent delegation rule** — verbatim from spec: top-level agent owns adversarial checkpoints; sub-agent internal checks don't replace them
  - **Handoff message format** — terse scannable format from spec §Agent Handoff Format; includes:
    - One-liner for `budget_status.warning_level` when non-`none`
    - Banner when `degraded: true` noting lost provider coverage
    - Banner when `dedup_method: "deterministic"` noting consolidation quality
    - Banner when `diversity_warning: true` (single-provider review)
    - Banner when `pricing_unavailable: true`

**Success check:** Claude Code session with skill installed, given non-trivial coding task, produces handoff matching the format including relevant banners when those flags fire.

### Phase 9 — Packaging and Install

**Deliverable:** Developer installs with two commands.

```
pipx install dvad-agent-native
dvad-agent install
```

The `install` bootstrap (`scripts/install.py` invoked by the CLI):

- Writes MCP server entry to Claude Code's config (default `~/.claude/settings.json` or project-local equivalent)
- **Creates a timestamped backup of the existing config first** before any modification
- Supports `--dry-run` that prints intended changes without writing
- Merges into an existing settings file with other MCP servers already configured — does not overwrite
- Copies `skill/dvad.md` to `~/.claude/skills/dvad.md`
- **On any step failure:** prints the exact JSON/file to paste as a manual fallback so the user can complete manually without being stuck

README sections: 30-second pitch, install (two commands), one demo, link to spec and roadmap, platform note (Linux/macOS/WSL), call-out that the CLI is development infrastructure and not the product surface.

**Success check:** Clean shell → README instructions → working install. Fresh settings.json created correctly. Pre-existing settings.json with other MCP servers gets the dvad entry merged without losing the others. `--dry-run` prints but writes nothing. Write failure produces a usable paste-fallback output.

### Phase 10 — Smoke Test

Ownership split per conversation Exchange 20.

**Phase 10a (Brian + this agent, mechanical correctness):**

1. Install MCP server locally
2. Open VS Code with Claude Code extension
3. Clone a small public repo (Flask todo, Express starter, etc.)
4. `dvad-agent install` in the workspace
5. Give the agent a non-trivial task
6. Watch the cycle: plan → dvad → revised plan → implementation → dvad → handoff
7. Verify: server starts, tools register, calls complete, findings return, handoff renders with all banners correctly, budget tracks across calls, degraded fires on injected provider failure, slow-review warning fires on injected latency, `oversize_input` fires on injected oversized input

**Phase 10b (v2 collaborator, experience judgment):**

8. Does the handoff feel right in daily IDE flow?
9. Ship / iterate / this-specific-thing-is-off

**Explicit non-tasks for Brian:** don't deep-learn VS Code; don't deep-study the test repo's architecture; don't write tests for dvad itself during smoke testing.

---

## 4. Port Map (Revised)

| dvad core file | What to port | Status |
|---|---|---|
| `providers.py` — `call_anthropic` | httpx call, retry/backoff, 529 budget, usage dict; ability to **explicitly disable** thinking | Port |
| `providers.py` — `call_openai_compatible` | httpx to `/chat/completions`, usage attribution | Port |
| `providers.py` — `call_openai_responses` | httpx to `/responses` — **required** for gpt-5 / o3 (reasoning series) | Port |
| `providers.py` — `call_minimax` | — | **Skip for v1.** MiniMax not in zero-config default table (§8 Non-Goals, §10.8). Port later if/when added as default. |
| `providers.py` — `call_google` | — | **Net-new code** if OpenAI-compat evaluation fails. Evaluate compat endpoint first (Phase 2 gate). |
| `config.py` | Env-key resolution, XDG path handling, `ModelConfig` shape | Port |
| `dedup.py` | Dedup prompt shape, response-to-groups structure, `format_points_for_dedup` | Port |
| `prompts.py` | Rubric-per-mode prompt structure, dedup prompt | Port (adapt per artifact_type list) |
| `cost.py` | Token estimator, `check_context_window` | Port |
| `output.py` | Markdown report structure inspiration | Port as inspiration |
| `parser.py` | JSON parsing patterns, `sanitize_json_output` | Port minimal |

**Rule:** port means read, understand the pattern, close the file, rewrite against the new package structure. Do not `from devils_advocate import ...`.

---

## 5. Testing Strategy

Target: ~220 tests total. Runs in <10s without real API calls. Small by design.

**Unit tests** (pure functions):
- Secrets regex (positive + negative + entropy gate, per-channel labeling)
- Cost estimation (including `None` for unavailable pricing), context-window checks
- Outcome derivation matrix (all severity combinations × all degraded scenarios)
- `degraded` flag logic: pre-failure state relative (single-provider + multi-provider + mixed cases)
- Category normalization table
- Severity/category merge rules
- Deterministic dedup algorithm: Jaccard 0.7 + bigram 0.3 rule; reproducible across runs
- Budget file I/O: calendar-day rollover, threshold transitions, fail-closed on corruption, init on missing, `DVAD_BUDGET_DAILY=0` behavior, `asyncio.Lock` + `fcntl.flock` interaction
- Path validation: `../..`, symlinks escaping `repo_root`, absolute paths, size caps, `repo_root` itself being `/` or empty
- Diversity warning derivation
- Log redaction filter (API keys scrubbed from records)
- `os.umask` set at startup

**Integration tests** (mocked httpx):
- Partial failure paths (0, 1, 2, 3 reviewers failing)
- Budget abort (per-review, daily)
- Dedup model failure → reviewer-model fallback → deterministic fallback
- Dedup sub-budget timeout → deterministic fallback
- Deadline exceeded → stragglers cancelled → ≥2 success rule
- JSON parse failure → `ReviewerError` with `raw_response`
- Schema validation failure → `ReviewerError` with `error_type: "schema_invalid"`
- Secrets detected in each channel (artifact, instructions, reference_files)
- Secrets detected in dedup payload (reviewer echoed user content)
- `oversize_input` trigger with real context-window math (no silent truncation)
- `invalid_request` for reference_files without repo_root
- Slow-review warning fires at 20s under injected delay
- `pricing_unavailable` path when a model has no cost metadata

**Schema contract tests** (pinned JSON-schema fixtures — one per `ToolResponse` variant):
- `ok` (including combinations: `degraded: true`, `dedup_method: "deterministic"`, `pricing_unavailable: true`, redaction present)
- `setup_required`
- `skipped_budget`
- `skipped_secrets`
- `oversize_input`
- `failed_review`
- `invalid_request`

**MCP lifecycle tests:**
- Startup failure → stderr message + non-zero exit
- Broken-pipe mid-review → task cancellation + partial-cost log
- Shutdown sequence: drain → cancel → httpx close → lock release

**Install command tests** (`test_install.py`):
- Fresh `~/.claude/settings.json` write
- Merge into existing settings file with other MCP servers
- Backup creation (timestamped)
- `--dry-run` output correctness
- Graceful failure with paste-fallback when directory doesn't exist or isn't writable

**Real-API smoke test** (manual, `DVAD_E2E=1`): pytest fixture that runs a review against real providers. Used sparingly.

---

## 6. Open Questions Carried Forward

1. **Dedup default = model-based with fast non-reasoning models.** Resolved. Deterministic (Jaccard 0.7 + bigram 0.3) is the spec §10 fallback chain.
2. **Reference file inference stays out of v1.** Agent passes `reference_files` explicitly with `repo_root`. Spec's parameter description is marked stale in §10.6.
3. **Single-provider diversity** — runs with `diversity_warning: true`, doesn't gate. Revisit with adoption data.
4. **Google OpenAI-compat vs native Gemini** — Phase 2 gate with four explicit criteria. Prefer compat if all four pass.
5. **Native Windows support** — v2, alongside IDE-native push. v1 is Linux/macOS/WSL.

---

## 7. Risk Register (Revised)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| p95 review latency exceeds 30s | Medium | High | Explicit stage budgets (§3 Phase 4), non-reasoning dedup models, pipelined dedup from 2/3-complete, 45s deadline with 17s slack over p95, 20s slow-review warning for UX |
| Secrets regex false positives block legitimate reviews | Medium | Medium | Entropy gate; `redact` mode; `DVAD_SECRETS_MODE=skip` env escape hatch |
| MCP progress notifications don't work in some clients | Medium | Low | `as_completed` drives correctness; no-op fallback for progress |
| Provider API shape drift | Low | Medium | httpx direct = HTTP errors not SDK exceptions; pin API versions in headers; `probe` command for explicit validation |
| JSON output parsing fails inconsistently | Medium | Medium | Three-tier strategy (native → strip fences → `ReviewerError`) plus schema validation post-parse |
| First-run `setup_required` treated as tool error by MCP clients | Low | High | Return as success-with-data; contract test validates this |
| Path traversal via caller-supplied paths | Medium | High | `realpath` resolution under validated `repo_root`; `repo_root` itself canonical absolute directory (not `/`); reject absolute/traversal/symlink-escape; size caps; test suite covers escape attempts |
| Concurrent MCP servers race on daily budget | Low | Low | `asyncio.Lock` + `fcntl.flock` via `asyncio.to_thread`; two-layer locking |
| Google provider implementation cost underestimated | Medium | Medium | Phase 2 gate evaluates compat endpoint first with 4 explicit criteria; only falls through to native Gemini if criteria fail |
| Reasoning model mistakenly assigned to dedup | Medium | Medium | Default table explicitly selects non-reasoning dedup models; `thinking_enabled=False` default; docstring warning |
| API keys leaked in DEBUG logs | Medium | High | `logging.Filter` scrubs Authorization / x-api-key / x-goog-api-key headers before emission; tests assert redaction |
| Budget file tampering bypasses cap | Low | High | Corruption → fail closed; filesystem permissions 0600 on file + 0700 on dir + umask 0o077 at startup |
| Unknown-model pricing mishandled | Medium | Medium | `estimate_cost` returns `None` for unknown; response surfaces `pricing_unavailable: true`; never invent a conservative default |
| Silent truncation obscures review input | N/A | N/A | Removed — plan now returns `oversize_input` and lets caller decide |
| Pricing table drift as providers change prices | Medium | Low | Maintenance item in risk register; `pricing_unavailable` handles the degraded case gracefully; table versioned with package |
| Scope creep toward v2 | High | Critical | Spec §Non-Goals + plan §8 + roadmap exist as law. |

---

## 8. Explicit Non-Goals (v1)

Per spec §Non-Goals and plan decisions:

- IDE-native integration (gutter annotations, squigglies, extensions) — v2
- CI/CD integration (GitHub Actions, PR bots) — v2
- Hosted service / SaaS
- Changes to dvad core
- Automatic reference file discovery / repo crawling
- Custom rubrics via MCP
- Multi-turn review sessions
- Structured `parent_review_id` delta computation (metadata linkage only)
- Batch / multi-artifact review
- Finding location hints (`file_path`, `approx_lines`)
- **Native Windows support** (Linux/macOS/WSL only in v1) — v2
- **MiniMax as zero-config default provider** — roadmap (core has `call_minimax`; defaults scope to Anthropic/OpenAI/Google for v1)
- **Externalized `CATEGORY_NORMALIZATION_TABLE`** — v2 with explicit override contract if real-world data shows the hardcoded table can't keep up
- Anything on `roadmap.md` v2/v3 lists

---

## 9. Success Criteria

1. Two-command install works for a developer with ≥2 provider keys (or one key providing ≥2 distinct reviewer models)
2. Agent-invoked `dvad_review` returns structured findings in <30s p50 for <5K-token artifact
3. Handoff with adversarial trail (including banners for degraded/diversity/deterministic/pricing as applicable) is visibly better than without — to the point where "done, tests pass" feels reckless by comparison
4. A contributor can read the codebase in one sitting and hold the architecture in their head
5. Meta-success: a dvad review of this plan produces findings that improve it (currently at 4 rounds, 86 findings, demonstrably improved across v1→v2→v3)

---

## 10. Decisions Made (v2 + v3)

### 10.1 Drop the 30-minute-read stopwatch (v2)

`Outcome` is content severity only. `degraded` is a separate boolean. Two signals preserved independently.

### 10.2 `outcome` and `degraded` are two independent fields (v2)

`Outcome` is content severity only (`clean | caution | critical_found`). `degraded` is a separate boolean on the `ok` response.

### 10.3 Budget: disk-persisted, calendar day in local time, no override (v2)

Daily spend persisted per-calendar-day in local timezone. `DVAD_BUDGET_DAILY=0` disables the cap.

### 10.4 Budget warning thresholds surfaced in-response, not as prompts (v2)

70% `soft`, 85% `hard`, inline in response for agent handoff. No interruptive prompts.

### 10.5 Model-based dedup primary, non-reasoning models, pipelined from 2/3-complete (v2)

Non-reasoning dedup defaults (haiku / gpt-4o-mini / gemini-2.5-flash). Dedup runs once after fan-out closes. Deterministic fallback per spec §10.

### 10.6 Platform: Linux/macOS/WSL in v1; native Windows in v2 (v3)

**Decision:** Declare Linux/macOS/WSL as supported platforms. Native Windows support (~50 LoC platform abstraction, CI matrix expansion, testing burden) deferred to v2 alongside IDE-native push.

**Rationale:** The v1 codebase uses `fcntl`, POSIX permissions, XDG paths — POSIX-shaped throughout. Swapping `fcntl.flock` for `msvcrt.locking` is trivial (~20 LoC), but it's only one incompatibility; claiming first-class Windows support based on just the lock swap would be misleading. WSL gives Windows developers a first-class POSIX shim that most Python-tooling-savvy Windows users already have. The addressable demographic for an agentic-AI MCP server skews Mac/Linux/WSL already. Native Windows is a v2 platform pass, not v1 scope.

### 10.7 45s deadline, 20s slow-review warning, enforced sub-budgets (v3)

**Decision:** Hard deadline 45s. Fan-out sub-budget ~25s. Dedup sub-budget ~10s. Slow-review warning fires at 20s. Sub-budgets are enforced (cancellation + ReviewerError), not advisory.

**Rationale:** Pairings 3+4 proposed tightening the deadline to 35s to match the <30s performance target. Rejected: `providers.py` budgets up to 30s for 529 overload retries (`_529_BUDGET_SECONDS = 30.0`), so a 35s overall cap would cancel reviews that the partial-result design is specifically built to salvage via the ≥2-success rule. Compensation: enforce sub-budgets explicitly + emit a slow-review warning at 20s so observability on the target exists even when the hard deadline doesn't fire. The 20s threshold catches the UX pain point where silent terminals feel dead, well before the hard cap.

### 10.8 Pricing-unavailable warning, not conservative default (v3)

**Decision:** When `estimate_cost` has no pricing metadata for a model, return `None` and surface `pricing_unavailable: true` in the response. Never invent a conservative default price.

**Rationale:** A conservative default would falsely block legitimate proxy-routed or local-model work. Plan supports `OPENAI_BASE_URL` for OpenRouter/Groq/vLLM users; many of those proxies route to cents-per-million-tokens models or free local models. An invented high default would create false `skipped_budget` for legitimate tiny-cost or zero-cost work. Warning path preserves budget integrity by refusing to guess.

### 10.9 `reference_files` requires `repo_root` (v3)

**Decision:** If `reference_files` is non-empty, `repo_root` must be supplied and must be a canonical absolute existing directory (not `/`, not empty). Otherwise, return `ToolResponse{status: "invalid_request"}` with structured reason.

**Rationale:** Path-validation requires a trusted root for `realpath` containment checks. Without `repo_root`, the implementation would either guess a base directory (weakening traversal guarantees) or accept paths blindly (allowing `/etc/passwd` reads). This is a documented spec deviation — spec §1 allows `reference_files` without `repo_root`. Documented in §10.11 Spec Deviations.

### 10.10 `degraded` semantics relative to pre-failure state (v3)

**Decision:** `degraded: true` when ≥1 reviewer failed AND a provider represented in the planned reviewer set before the failure is no longer represented after. Single-provider setups never get `degraded: true` (they already carry `diversity_warning`). Multi-provider setups where all providers remain represented after a redundant reviewer failure → `degraded: false`.

**Rationale:** Pairing 4 identified that the v2 definition ("lack cross-provider diversity") was ambiguous for single-provider setups. A relative-to-pre-failure definition distinguishes "we planned for 3 providers but lost one" from "we planned for 1 provider and one of its models failed" — those are semantically different and deserve different signals. Single-provider coverage reduction is already visible through `diversity_warning` + `reviewer_errors`, so adding a third flag for it would bloat the API without adding information.

### 10.11 Budget file: corrupted fails closed, missing initializes (v3)

**Decision:** If today's budget file exists but fails JSON parse or schema check → `skipped_budget` (fail closed, don't proceed). If today's file doesn't exist → initialize to $0 and proceed.

**Rationale:** Corruption may indicate tampering or disk error; refusing to proceed prevents unaccounted spend that could bypass the daily cap. Missing file is the normal first-run or post-midnight-rollover state; treating it as fatal would block legitimate use. The per-day file architecture makes this distinction clean: today's file is expected to not exist before today's first review.

---

## 10.12 Spec Deviations (consolidated)

Intentional divergences from `spec.v3.md`. Plan supersedes spec on these points until the next spec revision reconciles them.

| Area | Spec says | Plan says | Rationale |
|---|---|---|---|
| `outcome` enum | 4 values (`clean`, `caution`, `critical_found`, `degraded`) | 3 values; `degraded` is a separate boolean flag | §10.2: content severity and coverage health are orthogonal signals; a single enum would hide one when both apply |
| `ToolResponse` | Flat return objects per tool | Discriminated union with required `status` field | §3 Phase 1: multiple non-review-complete paths (`setup_required`, `skipped_budget`, etc.) need a clean top-level shape for agents to branch on |
| `reference_files` without `repo_root` | Allowed per parameter description | Rejected via `invalid_request` | §10.9: path validation requires a trusted root |
| `reference_files` auto-inference | "If omitted, dvad infers from imports/references in the artifact" | No inference; agent passes explicitly or reviewer works with artifact alone | Spec's own §Non-Goals agrees; parameter description is stale |
| Additional `ReviewResult` fields | Not documented in spec example | `dedup_method`, `dedup_skipped`, `redacted_locations`, `original_artifact_sha256`, `budget_status`, `diversity_warning`, `pricing_unavailable` are part of public contract | §3 Phase 6: agents need these signals for handoff; spec example was incomplete |
| `dvad_config` response shape | Loosely defined | Includes `secrets_handling` mode, `platform`, pricing-availability per model | Public contract — agents discover server state without trial and error |
| Budget "stateless" | Spec §8: state tracked in-memory, resets on restart | Disk-persisted per calendar day | §10.3: "resets on restart" is not what humans mean by "daily cap"; persistence is bookkeeping, not feature creep |
| MiniMax provider | Listed in core `providers.py` | Not in v1 zero-config defaults | §8 Non-Goals: zero-config scopes to Anthropic/OpenAI/Google; MiniMax is roadmap |

---

## 11. Prior Review Dispositions (all 4 pairings)

86 findings across 4 rounds. Dispositions consolidated.

### Accepted and folded into v3

All items below are reflected in the plan above.

**From pairings 1–2 (attacking plan.v1, ~36 items):**

- Three-tier JSON parsing (native → strip fences → ReviewerError with raw_response)
- `call_openai_responses` added to Phase 2 (gpt-5 uses /v1/responses)
- `call_google` reclassified as net-new code with OpenAI-compat evaluation first
- Discriminated `ToolResponse` union with all status variants
- Path validation for `reference_files` (realpath, containment, size caps)
- `reference_files` flow fully defined (read, secrets-scan, concatenate, include in cost/context)
- Secrets scanner operates on strings (`scan(content: str)`); CLI wraps for file input
- `DVAD_SECRETS_MODE` env override for zero-config escape hatch
- Context-window preflight for reviewers AND dedup; `oversize_input` status
- Overall `review_deadline` with fan-out and dedup sub-budgets
- `asyncio.as_completed` instead of `gather` (progress compatibility)
- Dedup merge rules (severity = max, category = modal + tie-break)
- `CATEGORY_NORMALIZATION_TABLE` (hardcoded, versioned with package)
- Deterministic dedup algorithm precisely specified
- `minimum_met` redefined: ≥2 distinct reviewer models
- `diversity_warning` in all three tool responses
- `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` proxy support
- Non-reasoning dedup defaults per provider (haiku / gpt-4o-mini / gemini-2.5-flash)
- Budget disk persistence, calendar day, local time rollover
- Budget warning thresholds (70% / 85%) surfaced in response
- `DVAD_BUDGET_DAILY=0` disables cap
- Explicit thinking-disable for Anthropic (not just strip budget logic)
- Persistence opt-in, metadata-only default, 0600 files, redaction mapping never persisted
- Pipelined dedup from 2/3-complete boundary
- Model validation via `probe` command
- Logging to stderr only (MCP stdio hazard)
- `httpx.AsyncClient` lifecycle with drain period
- `dvad-agent install` bootstrap with paste fallback
- Test files expanded (test_output, test_cost, test_budget)
- Contract tests per `ToolResponse` variant
- Category enum clarified (9 values including `other`)
- Reviewer output hard-capped (explicit `max_output_tokens`)
- `secrets_handling` default `abort`, config-layer only (not per-call)
- `degraded` never masks content severity

**From pairings 3–4 (attacking plan.v2, ~30 items):**

- `ReviewContext` dataclass defined in `types.py`
- Default model table: two reviewer-role models per provider (fixes minimum_met contradiction)
- `max_output_tokens` explicitly threaded through `call_model` (not prompt-instructed)
- Dedup runs exactly once after fan-out closes on final reviewer set (no merge-in-flight)
- Silent truncation removed from context-window preflight (return `oversize_input`)
- Secrets scan: per distinct outbound payload type (reviewer payload + dedup payload), not per HTTP call
- Jaccard threshold raised to 0.7 + bigram 0.3 secondary signal
- `repo_root` validation: canonical absolute directory, not `/`, exists
- `reference_files` size caps: 1 MiB per file, 5 MiB total
- Two-layer locking: `asyncio.Lock` (in-process) + `fcntl.flock` via `asyncio.to_thread` (cross-process)
- Schema validation step after JSON parse (reject semantically-invalid-but-syntactically-valid JSON)
- API key log redaction filter
- `os.umask(0o077)` at server/CLI startup; `os.makedirs(mode=0o700)`; check existing-dir perms
- Google OpenAI-compat endpoint evaluation criteria (4 explicit pass/fail tests)
- Google provider identity/transport split (`use_openai_compat` transport hint; `provider="google"` preserved)
- `httpx` shutdown sequence explicit (stop new, await, cancel, close)
- Broken-pipe mid-review cancellation with partial-cost log
- MCP startup failure to stderr + non-zero exit
- Install command integration tests
- Slow-review warning at 20s (lowered from 30s on Brian's UX reasoning)
- Sub-budget enforcement explicit, not advisory
- Unknown-model pricing → `pricing_unavailable` warning (not a default)
- `dvad_estimate` dedup cost heuristic documented
- Latency budget math rewritten with explicit overlap notation
- Deterministic dedup markdown caveat when `dedup_method: "deterministic"`
- `secrets_handling` in `dvad_config` output documented as public contract
- Full `ReviewResult` field set documented as public contract
- Spec Deviations register as §10.12
- `thinking_enabled: bool = False` default (positive naming; inverse of prior v2 `thinking_disabled`)
- Budget corruption → fail closed; missing → initialize
- Platform constraint: Linux/macOS/WSL in v1

### Rejected — do not re-raise without new information

- **Native Windows support in v1.** §10.6: ~50 LoC platform abstraction is tractable but belongs in v2 alongside IDE-native work. WSL serves the current user demographic.
- **MiniMax in default model table.** §8 Non-Goals: zero-config scopes to 3 providers in v1; core `providers.py` has `call_minimax` for future use.
- **Externalize `CATEGORY_NORMALIZATION_TABLE` to YAML.** §10.1 Phase 1 Types: deterministic normalization is part of the tool contract; user-editable tables break reproducibility across environments. Revisit in v2 with an explicit override contract.
- **Disk-persisted redaction mappings.** Security risk; `original_artifact_sha256` + `redacted_locations` achieve cross-reference without persisting the secret.
- **Per-call `secrets_handling` parameter in `dvad_review`.** LLM-driven caller could downgrade the security control; config + env only.
- **Automatic reference-file discovery / repo crawling.** Explicit spec §Non-Goals.
- **Model-based dedup skipped entirely ("always deterministic").** Breaks consensus accuracy. §10.5 + v3 empirical latency budget.
- **24-hour sliding-window budget.** Not what humans mean by "daily."
- **Single-field outcome with `degraded` as a precedence tier.** Masks signal.
- **Timezone override for budget rollover.** Configuration fatigue.
- **Embedding-based semantic similarity in deterministic dedup.** 100MB+ dependency; violates minimal-deps constraint.
- **Prompt injection pre-scan.** Multi-model adversarial design is itself the defense; regex is trivially bypassed + false-positives on legitimate content.
- **Dedup on raw unparsed reviewer output.** Dedup prompt requires structured fields post-parse.
- **Interactive budget-approval prompts.** Breaks silent-infrastructure UX for agent-invoked reviews.
- **Merging late reviewer findings into in-flight dedup.** HTTP requests cannot be mutated after dispatch; pinned to "one dedup pass on final reviewer set."
- **Silent truncation of reference files / artifact to fit context windows.** Changes input semantics without surfacing it; `oversize_input` lets caller decide.
- **Conservative default price for unknown models.** Would falsely block proxy-routed / local-model work.
- **Lowering hard deadline from 45s to 35s.** Cancels reviews that partial-result semantics are designed to salvage under 529 retries; §10.7.
- **Adding a third `coverage_reduced` signal for single-provider setups.** `diversity_warning` + `reviewer_errors` already cover it; §10.10.

### Escalated and resolved

10 escalated items from pairings 3+4 all resolved via decisions in §10 and accepted items above. Pairing 1+2 escalated items (7) similarly resolved in v2 → v3 refinements.

---

## 12. Next Steps

1. Optionally run this plan (v3) through dvad one more time with a fresh pairing. Signal expectation: further refinements, not structural catches. Diminishing returns consistent with the round-3 / round-4 pattern observed.
2. If pairings 5+ produce only refinements (no structural contradictions), move to Phase 0.
3. Phase 0 → Phase 10 per §3. Each phase's success check is the gate.
4. Phase 10a demo recorded. Handoff to v2 collaborator for Phase 10b judgment.
5. Ship when Phase 10 passes.

---

*Plan v3. Supersedes v1 and v2. Ready for adversarial review or implementation.*
