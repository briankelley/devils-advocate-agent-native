# Findings — 2026-04-23 (Session 2)

**Audience:** Future Claude session picking up smoke testing or further work.
**Prior context:** `docs/handoff.2026-04-23.md` (session 1), `docs/conversation.01.md` (strategic origin).
**Session goal:** Resolve blockers from session 1 handoff, get to smoke-test readiness.

---

## Blockers resolved

### 1. Anthropic API key

The key was valid all along. Session 1 saw a truncated paste — the `sk-ant-api03-` prefix wrapped across terminal lines and got clipped. Full key works. All three providers (Anthropic, OpenAI, Google) confirmed via probe.

### 2. Default model table was stale

Session 1 defaulted to gpt-4o, gpt-4.1, gpt-4o-mini (OpenAI) and gemini-2.5-flash, gemini-2.5-flash-lite (Google) because gpt-5/o3 hit an org-verification wall. These models are a generation behind what's current in April 2026 — more expensive and less capable than their successors.

**Updated defaults (now in `config.py`):**

| Role | Old default | New default | Rationale |
|---|---|---|---|
| Anthropic reviewer | claude-sonnet-4-6, claude-opus-4-7 | **claude-opus-4-7, claude-opus-4-6** | Sonnet has been unreliable since early 2026 — quality regressions. Brian's direct experience: "opus / haiku or nothing." |
| Anthropic dedup | claude-haiku-4-5-20251001 | claude-haiku-4-5-20251001 (unchanged) | Works, fast (2.2s), cheap |
| OpenAI reviewer | gpt-4o, gpt-4.1 | **gpt-5.2, gpt-5.4-mini** | Current generation, cheaper, both thinking=false |
| OpenAI dedup | gpt-4o-mini | **gpt-5.4-nano** | $0.20/$1.25 per MTok, fastest dedup candidate (1.9s) |
| Google reviewer | gemini-2.5-flash, gemini-2.5-flash-lite | **gemini-3-flash-preview, gemini-2.5-flash** | gemini-3-flash is current gen. gemini-2.5-flash-lite was producing malformed JSON (parse failures). gemini-3-pro-preview and gemini-2.5-pro both refuse thinking-disabled mode ("Budget 0 is invalid. This model only works in thinking mode.") — the Pro tier across Gemini generations consistently requires thinking. |
| Google dedup | gemini-2.5-flash | **gemini-3-flash-preview** | Current gen, works, 3.5s |

### 3. OpenAI `max_tokens` → `max_completion_tokens`

GPT-5.x models reject the deprecated `max_tokens` parameter. They require `max_completion_tokens`. Fixed in `call_openai_compatible` in `providers.py`. This was a hard 400 error on every GPT-5.x call.

### 4. Anthropic max_output_tokens too low

At 1500 max_output_tokens, verbose Anthropic models (especially when producing 10+ findings with detail fields) would exceed the token cap mid-JSON, resulting in truncated output that fails parse validation. Bumped to 3000 for Anthropic reviewer role. This eliminated the only reviewer FAIL in the verification run.

---

## Bugs found and fixed

### Sequential dedup fallback (the big one)

`_run_dedup` in `review.py` iterated dedup candidates sequentially, giving each one the full `dedup_window` timeout (10s). If candidate 1 timed out at 10s, candidate 2 got a fresh 10s, candidate 3 got another 10s. Total: 30s for a phase budgeted at 10s. This was the primary cause of the 50+ second review durations observed in session 1 and early session 2.

**Fix:** Parallel fan-out of all dedup candidates using `asyncio.wait` with `FIRST_COMPLETED`. First valid result wins, others are cancelled. The 10s `dedup_window` now applies as a hard cap across all candidates simultaneously.

**Result:** Dedup phase dropped from ~25s (sequential) to ~2-4s (parallel, fastest candidate wins).

### `asyncio.as_completed` dict lookup

Initial parallel dedup implementation used `asyncio.as_completed`, which yields wrapper coroutines — not the original Task objects used as dict keys. Caused `KeyError` on every successful dedup. Fixed by switching to `asyncio.wait` with `FIRST_COMPLETED`, which returns actual Task objects.

---

## Anthropic API optimizations added

### Prompt caching

System prompt now tagged with `cache_control: {"type": "ephemeral"}` in `call_anthropic`. The system prompt is sent as an array of content blocks (required for cache_control) rather than a plain string. When two Anthropic reviewers run in the same fan-out, the second call should hit the cache — up to 85% latency reduction and 90% cost reduction on the cached portion. Minimum cacheable size is 2048-4096 tokens depending on model; our reviewer system prompt + rubric exceeds this.

### service_tier

`"service_tier": "auto"` added to all Anthropic API calls. Uses Priority Tier capacity when available, reducing 529 (overloaded) errors during peak demand.

---

## Full model-role verification results

Every model in every assigned role tested with real reviewer/dedup prompts against the boardfoot sample plan. No time caps — 120s httpx timeout, 180s overall. All models ran in parallel.

### Reviewers

| Model | Provider | Time | Findings | Valid | Cost |
|---|---|---|---|---|---|
| gpt-5.4-mini | OpenAI | 3.3s | 5 | PASS | $0.003 |
| gemini-3-flash-preview | Google | 6.7s | 7 | PASS | $0.005 |
| gemini-2.5-flash | Google | 7.9s | 9 | PASS | $0.004 |
| gpt-5.2 | OpenAI | 26.0s | 14 | PASS | $0.022 |
| claude-opus-4-6 | Anthropic | 29.1s | 11 | PASS | $0.062 |
| claude-opus-4-7 | Anthropic | 35.9s | 13 | PASS | $0.055 |

### Dedup

| Model | Provider | Time | Groups | Valid |
|---|---|---|---|---|
| gpt-5.4-nano | OpenAI | 2.0s | 4 | PASS |
| claude-haiku-4-5 | Anthropic | 2.2s | 4 | PASS |
| gemini-3-flash-preview | Google | 3.5s | 4 | PASS |

### Key observations

- Google and OpenAI non-reasoning models are fast (3-8s). They will consistently complete within any reasonable fan-out budget.
- gpt-5.2 is borderline at 26s — sometimes makes the 25s fan-out, sometimes doesn't. Load dependent.
- Anthropic Opus models are 29-36s. They will exceed the current 25s fan-out budget on most calls. This is provider-side latency under current demand, not a code issue.
- When Anthropic reviewers get cancelled by the fan-out budget, the review completes as `degraded: true` with the remaining providers. This is working as designed — degraded is honest, not broken.
- All three dedup models complete in under 4 seconds. The earlier dedup failures were entirely caused by the sequential fallback bug, not model issues.

---

## Latency landscape (honest assessment)

The plan's p50 <30s target assumed three reviewers completing in parallel. The reality in April 2026:

- With Google + OpenAI only (4 reviewers, no Anthropic): **~8-13s total** including dedup. Well under 30s.
- With all three providers (6 reviewers): Anthropic models exceed the 25s fan-out budget, get cancelled, review completes degraded at **~30-35s total**. Close to target but consistently over due to dedup phase.
- Anthropic is experiencing extreme demand. This affects all their API consumers, not just dvad. The 25s fan-out budget is a code-side constraint; the provider-side latency is not something we can fix.

Brian's position: time caps are a tunable for later. The product works. Every model produces valid output when given time. Latency optimization is iteration, not a blocker.

---

## Provider expansion notes

Brian expressed interest in expanding the default provider pool to include Chinese model providers (DeepSeek, Moonshot/Kimi, ZhipuAI/GLM, MiniMax). These are already in his dvad core `models.yaml` and work through OpenAI-compatible endpoints. They may lack the precision of frontier Western models but are far from unusable, and given the current performance landscape (Western providers under heavy load), they could provide faster response times with acceptable quality for adversarial review.

From a code perspective, adding these providers requires:
- New env var detection in `config.py` (e.g., `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `ZAI_API_KEY`, `MINIMAX_API_KEY`)
- Default model entries with appropriate pricing and context windows
- MiniMax needs a dedicated provider function (non-OpenAI-compatible API shape); the others route through `call_openai_compatible` with custom `api_base`

This is a post-smoke-test item. The architecture supports it cleanly — the reviewer fan-out doesn't care where models come from.

---

## Files changed in this session

| File | Changes |
|---|---|
| `src/dvad_agent/config.py` | Default model table updated (opus, gpt-5.x, gemini-3.x); old models removed |
| `src/dvad_agent/providers.py` | `max_tokens` → `max_completion_tokens` for OpenAI compat; prompt caching + `service_tier` for Anthropic |
| `src/dvad_agent/review.py` | Sequential dedup → parallel dedup with `asyncio.wait(FIRST_COMPLETED)` |
| `tests/test_config.py` | Updated model assertions and comments to match new default table |
| `scripts/verify_roles.py` | New — parallel model-role verification script (not production code) |

All 71 tests pass. No test logic changes beyond updating hardcoded model names in assertions.

---

## What's next

Smoke testing per the plan in `~/.claude/projects/-home-kelleyb/memory/dvad-agent-native.md`. The 6-step sequence:

1. Install MCP server locally
2. Open VS Code with Claude Code extension
3. Clone a small public repo
4. `dvad-agent install` in the workspace
5. Give the agent a non-trivial task, watch the full cycle
6. Collaborator judges the handoff

Brian will start a fresh session for this. Future-you should read this findings doc, the original handoff (`docs/handoff.2026-04-23.md`), and the memory file before starting.

**Do not** revisit the model table decisions documented here without new evidence from real calls. They were validated with a full parallel verification run across all 9 models.
