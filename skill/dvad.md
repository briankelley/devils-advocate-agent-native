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

### Handling response variants

- `status: "ok"` — act on `findings[]`. Critical/high findings deserve explicit response in your handoff.
- `status: "setup_required"` — no keys detected. Report `setup_steps` to the human verbatim.
- `status: "skipped_budget"` — daily cap reached. Report it; continue task without the review (advisory, not a gate).
- `status: "skipped_secrets"` — secrets detected. Tell the human what patterns fired (without the secret values). Suggest they either remove the secrets or re-run with `DVAD_SECRETS_MODE=redact`.
- `status: "oversize_input"` — tell the human which models don't fit; offer to trim context or reference files.
- `status: "failed_review"` — fewer than 2 reviewers succeeded. Surface `reviewer_errors` in the handoff.
- `status: "invalid_request"` — fix the input and retry.

## Handoff format

When you finish a non-trivial task, include an adversarial trail in your handoff:

```
Adversarial review (dvad, lite mode, {models_used})

  Round 1 — plan stage
    [critical/3] <issue>  → <what you changed>
    [high/2]    <issue>   → <what you changed>

  Round 2 — implementation stage
    [critical/3] <issue>  → <what you changed>
    [low/1]     <issue>   → deferred, your call

  (total cost: ${cost_usd}, duration: {duration_seconds}s)
```

### Banners to surface to the human

- `degraded: true` → "One reviewer failed; cross-provider coverage reduced."
- `diversity_warning: true` → "Single-provider review; findings more correlated."
- `dedup_method: "deterministic"` → "Model-based dedup unavailable — same-category findings may have been conservatively merged."
- `pricing_unavailable: true` → "Cost figures incomplete (unknown model pricing)."
- `budget_status.warning_level: "soft"` → include a one-liner about daily spend.
- `budget_status.warning_level: "hard"` → call it out prominently; the human may want to pause.

## What dvad is not

- Not a gate. It's a checkpoint. You keep moving.
- Not a security scanner. Findings related to security are reviewer opinions, not audit conclusions.
- Not a substitute for your own judgment. Use the findings; don't defer to them.
