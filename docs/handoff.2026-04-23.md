# Handoff — 2026-04-23

**Audience:** future Claude session continuing the `dvad-agent-native` build.
**Author:** prior Claude session (Opus 4.7), during the initial implementation pass.
**Repo:** https://github.com/briankelley/devils-advocate-agent-native (live on `main`).
**Local path:** `/media/kelleyb/DATA2/code/tools/devils-advocate-agent-native/`

If you're reading this, Brian has probably pasted the opening conversation (voice/tone), this doc, and the repo link into your context. The memory file `~/.claude/projects/-home-kelleyb/memory/dvad-agent-native.md` has the strategic context and the VS Code smoke-testing plan — read that before you do anything material.

---

## What was built

Phases 0–9 of `docs/plan.v3.md` are implemented. 3,900 LoC production, 800 LoC tests, 71 tests passing in <1s. The design strictly matches spec.v3 + plan.v3 with the spec deviations documented in plan §10.12 preserved.

The layout is on disk and in the repo — don't re-read every module on pickup. The files whose design will surprise you:

- `src/dvad_agent/review.py` — the orchestrator. ~700 lines, carries the full pipeline from payload assembly through outcome derivation. Everything else is called from here.
- `src/dvad_agent/types.py` — `ToolResponse` is a discriminated union via a required `status` field. All MCP responses carry this shape.
- `src/dvad_agent/config.py` — default model table lives here. It's been swapped once already (see "Fixes driven by real calls" below); expect to swap it again as providers shift.
- `src/dvad_agent/install.py` — the `dvad-agent install` subcommand + the embedded skill template. Editing the skill means editing this file AND `skill/dvad.md`. Keep them in sync or export the skill from one.

Tests live under `tests/` and run clean with `cd /media/kelleyb/DATA2/code/tools/devils-advocate-agent-native && .venv/bin/pytest`.

## Fixes driven by real calls (2026-04-23 afternoon)

The plan was adversarially reviewed 4 times. It still needed real calls to shake out these:

1. **OpenAI Responses API changed its shape.** `response_format` moved to `text.format`. Fixed in `providers.py::call_openai_responses`. This is documented as a note in the code; if OpenAI changes it again you'll see HTTP 400 with "Unsupported parameter" in the error.

2. **Gemini 2.5 defaults thinking ON.** Non-reasoning reviewers with `max_output_tokens=1500` silently consume the budget on internal reasoning before emitting any visible JSON. Fix: `generationConfig.thinkingConfig.thinkingBudget: 0` when `thinking_enabled=False`. See `providers.py::call_google`.

3. **Gemini 2.5 Pro refuses thinking-disabled mode.** It returns `400: "Budget 0 is invalid. This model only works in thinking mode."` Pro is therefore not a viable non-reasoning reviewer in v1. It's been removed from the default reviewer table; a user who wants Pro can override via `models.yaml` with `thinking_enabled: true` and a higher `max_output_tokens` cap.

4. **gpt-5 / o3 require OpenAI org verification.** HTTP 400/404 with "organization must be verified". Default reviewers swapped to `gpt-4o` and `gpt-4.1`. When Brian verifies his OpenAI org, the reasoning-tier models can come back as a `models.yaml` override — don't re-pin them as defaults without checking account state first.

5. **Overall deadline wasn't enforced.** The fan-out sub-budget ran correctly but dedup + render could push total duration past 45s. `review.py` now passes `dedup_window = min(DEDUP_BUDGET, remaining_deadline)` into `_run_dedup`, so the overall 45s deadline actually holds now.

6. **GH secret-scanning rejected the first push.** Three test fixtures happened to match patterns the scanner cares about (AWS / Stripe / GitHub PAT). They're synthesized at runtime via string concatenation in tests now. No real keys were ever touched.

Current default model table:
- Anthropic: `claude-sonnet-4-6`, `claude-opus-4-7` (reviewers); `claude-haiku-4-5-20251001` (dedup)
- OpenAI: `gpt-4o`, `gpt-4.1` (reviewers); `gpt-4o-mini` (dedup)
- Google: `gemini-2.5-flash`, `gemini-2.5-flash-lite` (reviewers); flash also acts as dedup fallback when google-only.

## Verified end-to-end

Against `/home/kelleyb/Desktop/Board Foot Android App/boardfoot.sample.plan.md`:

- Status: `ok`, outcome `caution`
- 4 reviewers succeeded (Anthropic was skipped — see blockers)
- 8 findings after dedup: 1 high, 4 medium, 3 low
- Cost: $0.038 total
- Duration: 53.7s (pre-deadline fix — will be bounded by 45s now)
- Dedup ran model-based (not deterministic)
- Findings were substantive, not hallucinated — locale number format, concurrency on mutable state, absent tests [4/4 consensus], input validation, single-Activity maintainability

The pipeline works. The product is real.

## Blockers before VS Code smoke test

In the order Brian will likely want to address them:

1. **Anthropic API key failing auth (401).** The key format in the opening conversation (`CPTK5AuNikN_...`) does NOT match the standard `sk-ant-api03-...` shape. Could be a console/proxy key, could be revoked, could be a fat-finger paste. When Brian provides a working key, test with: `ANTHROPIC_API_KEY=<key> .venv/bin/dvad-agent probe --model claude-haiku-4-5-20251001`. Once Anthropic is online, re-run the boardfoot review and confirm the 3-provider fan-out completes under 45s.

2. **Latency investigation.** The 53.7s observation was with 4 reviewers (OpenAI×2 + Google×2). The plan's p50 <30s target assumed 3-way fan-out. Hypothesis: `gpt-4o` is the slow one. Quick test: `time .venv/bin/dvad-agent probe --model gpt-4o` vs `--model gpt-4.1`. If gpt-4o is the bottleneck and we can't tighten it, drop it from the default reviewer table. Under-budget is infrastructure; over-budget is UX failure.

3. **OpenAI org verification** — unlocks gpt-5/o3 as override options. Not a code fix.

Once (1) and (2) are resolved, VS Code smoke testing is the next step. The 6-step plan and the division-of-labor (Brian + Claude for steps 1–5, collaborator for 6) is in the memory file under "Smoke testing plan". Don't re-derive it.

## Do not

- Do NOT rewrite `review.py` to be "cleaner". It's as tight as it's going to get given the surface area (validate → secrets#1 → window → budget → fan-out → slow-warning → partial-failure → secrets#2 → dedup → outcome → degraded → render → persist). Refactors here get quoted to Brian as scope creep.
- Do NOT re-pin `gpt-5` / `o3` / `gemini-2.5-pro` as defaults without checking provider account state. They're known-broken for current account config.
- Do NOT treat the spec and plan as drafts. They've survived 8 adversarial review rounds across 6 SOTA models. Changes require evidence from real calls, not theoretical improvements.
- Do NOT add features from `docs/roadmap.md` (v2/v3). Scope creep was spec.v1's top rejected category for a reason.
- Do NOT touch `~/API_KEYS.vault`. Brian's personal reference file, human-eyes-only. Ask for a key if you need one.

## Voice / tone reminder

From the opening conversation (which Brian will paste if he wants you to absorb it directly): direct assessment, concrete bridges for gaps, no cheerleading. When Brian names a self-perceived weakness ("I'm not a real programmer"), don't wave it away and don't pile on — identify what's actually load-bearing and what isn't. The conversation's calibration is real because it's honest, not because it's encouraging.

## What's next, in two sentences

Get a working Anthropic key into the mix, re-run the boardfoot review with all three providers, and verify the latency lands under 30s p50. When that's clean, walk Brian through VS Code smoke testing per the plan in the memory file.
