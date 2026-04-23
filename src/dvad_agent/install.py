"""dvad-agent install — register the MCP server with Claude Code and drop the skill.

- Writes MCP server entry to Claude Code's settings.json (default: ~/.claude/settings.json)
- Creates a timestamped backup of the existing config before modification
- Merges into existing settings without overwriting other MCP servers
- Supports --dry-run
- On any failure, prints the exact JSON/file the user can paste manually
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path


DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
DEFAULT_SKILL_DIR = Path.home() / ".claude" / "skills"
SKILL_FILENAME = "dvad.md"


def _mcp_entry() -> dict:
    return {
        "command": "dvad-agent-mcp",
        "args": [],
    }


def _embedded_skill_body() -> str:
    """The shipped skill text. Kept in-source so the install command never
    needs to shell out to find the wheel's data files.
    """
    return _SKILL_TEMPLATE


def run_install(
    *,
    dry_run: bool = False,
    config_path: str | None = None,
    skill_dir: str | None = None,
) -> int:
    settings = Path(config_path) if config_path else DEFAULT_SETTINGS
    skills = Path(skill_dir) if skill_dir else DEFAULT_SKILL_DIR
    intended_skill = skills / SKILL_FILENAME

    existing: dict = {}
    if settings.exists():
        try:
            existing = json.loads(settings.read_text(encoding="utf-8") or "{}")
            if not isinstance(existing, dict):
                raise ValueError("settings.json root is not an object")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"Could not parse {settings}: {exc}\n"
                "Refusing to modify. Fix the file manually, or pass --dry-run to see the intended change.\n"
            )
            return 1

    # Merge-in our MCP server entry, preserving anything else.
    updated = dict(existing)
    mcp_block = dict(updated.get("mcpServers") or {})
    if "dvad" in mcp_block and mcp_block["dvad"] != _mcp_entry():
        existing_entry = mcp_block["dvad"]
        sys.stderr.write(
            "Existing 'dvad' MCP entry differs; it will be overwritten. Old value:\n"
            + json.dumps(existing_entry, indent=2) + "\n"
        )
    mcp_block["dvad"] = _mcp_entry()
    updated["mcpServers"] = mcp_block

    serialized = json.dumps(updated, indent=2) + "\n"

    print(f"→ settings: {settings}")
    print(f"→ skill:    {intended_skill}")
    if dry_run:
        print("\n--- DRY RUN ---\n")
        print("settings.json would become:")
        print(serialized)
        print("\n---\n")
        print(f"skill file {intended_skill} would contain ~{len(_embedded_skill_body())} bytes of skill content.")
        return 0

    # 1. Write settings (with backup).
    try:
        settings.parent.mkdir(parents=True, exist_ok=True)
        if settings.exists():
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = settings.with_name(f"{settings.name}.dvad-backup.{stamp}")
            shutil.copy2(settings, backup)
            print(f"✓ backup: {backup}")
        settings.write_text(serialized, encoding="utf-8")
        try:
            os.chmod(settings, 0o600)
        except OSError:
            pass
        print(f"✓ wrote {settings}")
    except OSError as exc:
        sys.stderr.write(f"could not write {settings}: {exc}\n")
        _print_paste_fallback(settings, serialized, intended_skill)
        return 1

    # 2. Write skill file.
    try:
        skills.mkdir(parents=True, exist_ok=True)
        intended_skill.write_text(_embedded_skill_body(), encoding="utf-8")
        try:
            os.chmod(intended_skill, 0o644)
        except OSError:
            pass
        print(f"✓ wrote {intended_skill}")
    except OSError as exc:
        sys.stderr.write(f"could not write {intended_skill}: {exc}\n")
        _print_paste_fallback(settings, serialized, intended_skill)
        return 1

    print("\nInstall complete. Restart your Claude Code session and run `dvad_config`.")
    return 0


def _print_paste_fallback(settings: Path, serialized: str, skill_path: Path) -> None:
    print("\n--- PASTE FALLBACK ---\n", file=sys.stderr)
    print(
        f"Copy the JSON below into {settings}:\n\n{serialized}\n",
        file=sys.stderr,
    )
    print(
        f"Then create {skill_path} with the content below:\n",
        file=sys.stderr,
    )
    print(_SKILL_TEMPLATE, file=sys.stderr)


# ─── Skill template (source of truth) ─────────────────────────────────────────


_SKILL_TEMPLATE = """\
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
"""
