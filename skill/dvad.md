---
name: dvad
description: Run adversarial multi-LLM review on plans, implementations, and decisions. Invoke at checkpoints — not as a gate, but as proof of thinking shipped with the work.
triggers: [dvad, review, adversarial, checkpoint]
---

# dvad — adversarial checkpoint

`dvad` is an MCP server exposing three tools:

- `dvad_review` — run an adversarial multi-LLM review of an artifact
- `dvad_estimate` — cost estimate for reviewing an artifact (no external calls)
- `dvad_config` — detected providers, models, budget, platform

All outcomes are **advisory**. `critical_found` means three models found a critical issue, not that you must stop. You decide what to do with findings — the point is to surface them in your handoff so the human reviewer doesn't have to guess what you considered.

## When to invoke

- **After drafting a plan** for a non-trivial task (schema changes, new dependencies, security-adjacent code, multi-file refactors).
- **After implementation** when the diff is >50 lines, touches schema, adds deps, or touches security-adjacent surfaces.
- **Before declaring a task "done"** when any of the above apply.

## Token economics

Under token-based pricing, every debugging loop has a price tag. A plan-stage
dvad review is a comparatively modest checkpoint that often prevents much larger
iterative debugging cycles downstream.

For token and cost projections specific to your current artifact and model set,
run `dvad_estimate` before committing to a review.

For non-trivial work (schema changes, new dependencies, security-adjacent code,
multi-file refactors): **draft a plan first, then run dvad_review on it before
writing code.** The plan checkpoint is the cheapest token investment in the task
lifecycle. For simple tasks where the correct path is obvious, skip the plan
and review the diff directly.

## When NOT to invoke

- Typo fixes, formatting, docs-only changes, comment additions.
- Exploratory scratch work you'll throw away.
- When the daily budget warning_level is `hard` — report that to the user, let them decide.

## Multi-agent delegation

If you are the top-level agent talking to the human, you own the adversarial checkpoints. If you delegated work to a sub-agent, review the sub-agent's output through `dvad_review` before presenting it to the human — the sub-agent's internal quality checks do not replace your checkpoint. The proof-of-thinking artifact lives in the handoff *you* deliver.

## How to call

```
dvad_review({
  artifact: "<plan text, diff, code, etc.>",
  artifact_type: "plan" | "spec" | "diff" | "code" | "decision" | "test",
  context: {
    project_name: "optional",
    repo_root: "/absolute/path",         // required if reference_files is set
    reference_files: ["relative/path.py"],
    instructions: "optional extra steering"
  },
  parent_review_id: "optional — links re-reviews"
})
```

## First invocation disclosure

On the first dvad call in a session, run `dvad_estimate` first and disclose
the projected cost to the human:

  "Running adversarial review on this plan. Estimated: ~{total_estimated_tokens}
  tokens, ~${total_estimated_cost_usd}. Proceeding."

This disclosure is informational. Proceed unless:
- `budget_status.warning_level` is `hard` (daily cap near exhaustion)
- The human has previously expressed cost sensitivity in this session

Subsequent invocations in the same session: proceed without disclosure, but
include actual token count and cost in every handoff.

### Handling response variants

- `status: "ok"` — act on `findings[]`. Critical/high findings deserve explicit response in your handoff.
- `status: "setup_required"` — no keys detected. Report `setup_steps` to the human verbatim.
- `status: "skipped_budget"` — daily cap reached. Report it; continue task without the review (advisory, not a gate).
- `status: "skipped_secrets"` — secrets detected. Tell the human what patterns fired (without the secret values). Suggest they either remove the secrets or re-run with `DVAD_SECRETS_MODE=redact`.
- `status: "oversize_input"` — tell the human which models don't fit; offer to trim context or reference files.
- `status: "failed_review"` — fewer than 2 reviewers succeeded. Surface `reviewer_errors` in the handoff.
- `status: "invalid_request"` — fix the input and retry.

## Handoff format — MANDATORY

When presenting dvad results to the human, you MUST use the format below. Do NOT summarize, rewrite, or flatten dvad findings into your own analysis. The human needs to see that these findings came from independent adversarial review, not from you.

### Header (always include)

```
--- dvad adversarial review ---
Models: {list all models from models_used, e.g. gemini-3-flash, gpt-5.4-mini, gemini-2.5-flash, gpt-5.2}
Providers: {count distinct providers, e.g. "2 providers (Google, OpenAI)"}
Outcome: {outcome} | Tokens: {tokens_total} | Duration: {duration_seconds}s | Cost: ${cost_usd}
```

If `tokens_total` is absent or zero in the response (e.g., older server version),
omit the Tokens segment and use: `Outcome: {outcome} | Duration: {duration_seconds}s | Cost: ${cost_usd}`

If `degraded: true`, add to the header:
```
Coverage: DEGRADED — {list timed-out/failed models from reviewer_errors and their providers}
```

If `diversity_warning: true`, add to the header:
```
Coverage: Single-provider only — findings may be more correlated than usual.
```

### Consensus key (include on first dvad handoff in a session)

```
Consensus: [n/N] = how many independent models flagged this issue.
  N/N = high confidence (multiple models, different providers, same conclusion)
  1/N = single-model opinion (may be valid, but no corroboration)
```

### Findings (always include)

List every finding. Do not omit, reorder, or editorialize. Use this format:

```
[severity · consensus · category] Issue title
  Detail from the review.
  Reported by: {models_reporting}
  → Your response: {what you changed, or "deferred — your call"}
```

Example:
```
[critical · 4/4 · security] Unbounded rate-limit map allows OOM via IP rotation
  The rateLimitBuckets object stores IPs indefinitely without eviction or TTL.
  An attacker rotating IPs can exhaust process memory.
  Reported by: gemini-2.5-flash, gemini-3-flash-preview, gpt-5.2, gpt-5.4-mini
  → Added LRU eviction with 10K entry cap and 60s TTL.

[high · 1/4 · security] Prototype pollution via express.json()
  express.json() without __proto__ guard could allow payload manipulation.
  Reported by: gemini-2.5-flash (single-model opinion — no corroboration)
  → Deferred. Modern Express mitigates this. Your call.
```

### Footer (always include)

```
--- end dvad review ---
This review was generated by dvad (adversarial multi-LLM review protocol).
Findings represent cross-model consensus, not single-model opinion.
Review ID: {review_id}
```

### Banners to surface when applicable

- `dedup_method: "deterministic"` → "Model-based dedup unavailable — same-category findings may have been conservatively merged."
- `pricing_unavailable: true` → "Cost figures incomplete (unknown model pricing)."
- `budget_status.warning_level: "soft"` → include a one-liner about daily spend.
- `budget_status.warning_level: "hard"` → call it out prominently; the human may want to pause.

## What dvad is not

- Not a gate. It's a checkpoint. You keep moving.
- Not a security scanner. Findings related to security are reviewer opinions, not audit conclusions.
- Not a substitute for your own judgment. Use the findings; don't defer to them.
- Not you. Do not blend dvad findings into your own commentary. Present them in the format above so the human can distinguish adversarial review from your analysis.

