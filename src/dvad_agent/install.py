"""dvad-agent install — register the MCP server with Claude Code and drop the skill.

- Writes MCP server entry to ~/.claude.json (the file Claude Code reads for
  MCP server config — NOT ~/.claude/settings.json, which is for permissions
  and other settings only)
- Resolves the full path to dvad-agent-mcp at install time so the MCP server
  works regardless of PATH at spawn time (VS Code desktop launch, etc.)
- Creates a timestamped backup of the existing config before modification
- Merges into existing projects/scopes without overwriting other MCP servers
- Supports --dry-run and --scope (user or local)
- On any failure, prints the exact JSON/file the user can paste manually
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path


DEFAULT_CLAUDE_JSON = Path.home() / ".claude.json"
DEFAULT_SKILL_DIR = Path.home() / ".claude" / "skills"
SKILL_FILENAME = "dvad.md"


def _resolve_binary() -> str:
    """Return the absolute path to dvad-agent-mcp if found on PATH,
    otherwise fall back to the bare command name."""
    binary = shutil.which("dvad-agent-mcp")
    return binary if binary else "dvad-agent-mcp"


def _detect_env_keys() -> dict[str, str]:
    """Detect API keys in the current environment to seed the MCP env block."""
    env: dict[str, str] = {}
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.environ.get(var)
        if val:
            env[var] = val
    for var in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        val = os.environ.get(var)
        if val:
            env[var] = val
    return env


def _mcp_entry() -> dict:
    env = _detect_env_keys()
    entry: dict = {
        "type": "stdio",
        "command": _resolve_binary(),
        "args": [],
    }
    if env:
        entry["env"] = env
    else:
        entry["env"] = {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        sys.stderr.write(
            "\n⚠ No API keys found in current environment.\n"
            "  Edit the 'env' block in ~/.claude.json to add your keys:\n"
            '    "ANTHROPIC_API_KEY": "sk-ant-...",\n'
            '    "OPENAI_API_KEY": "sk-...",\n'
            "  Then restart your Claude Code session.\n\n"
        )
    return entry


def _embedded_skill_body() -> str:
    """The shipped skill text. Kept in-source so the install command never
    needs to shell out to find the wheel's data files.
    """
    return _SKILL_TEMPLATE


def _build_project_key(cwd: str | None = None) -> str:
    """Build the project key Claude Code uses in ~/.claude.json.

    For user-scope installs this returns a wildcard that applies to all
    projects. For local-scope installs it returns the CWD path."""
    if cwd:
        return cwd
    return "*"


def run_install(
    *,
    dry_run: bool = False,
    config_path: str | None = None,
    skill_dir: str | None = None,
    scope: str = "user",
) -> int:
    claude_json = Path(config_path) if config_path else DEFAULT_CLAUDE_JSON
    skills = Path(skill_dir) if skill_dir else DEFAULT_SKILL_DIR
    intended_skill = skills / SKILL_FILENAME

    existing: dict = {}
    if claude_json.exists():
        try:
            existing = json.loads(claude_json.read_text(encoding="utf-8") or "{}")
            if not isinstance(existing, dict):
                raise ValueError(".claude.json root is not an object")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"Could not parse {claude_json}: {exc}\n"
                "Refusing to modify. Fix the file manually, or pass --dry-run to see the intended change.\n"
            )
            return 1

    # Build the MCP entry for this scope.
    entry = _mcp_entry()

    # Determine where in the file structure the entry goes.
    # ~/.claude.json uses a projects dict keyed by project path (or "*" for
    # user-scope). Each project has an mcpServers block.
    updated = dict(existing)

    if scope == "user":
        # User-scope: top-level mcpServers block.
        mcp_block = dict(updated.get("mcpServers") or {})
        if "dvad" in mcp_block and mcp_block["dvad"] != entry:
            sys.stderr.write(
                "Existing 'dvad' MCP entry differs; it will be overwritten. Old value:\n"
                + json.dumps(mcp_block["dvad"], indent=2) + "\n"
            )
        mcp_block["dvad"] = entry
        updated["mcpServers"] = mcp_block
    else:
        # Local-scope: under projects.<cwd>.mcpServers
        project_key = _build_project_key(os.getcwd())
        projects = dict(updated.get("projects") or {})
        proj = dict(projects.get(project_key) or {})
        mcp_block = dict(proj.get("mcpServers") or {})
        if "dvad" in mcp_block and mcp_block["dvad"] != entry:
            sys.stderr.write(
                "Existing 'dvad' MCP entry differs; it will be overwritten. Old value:\n"
                + json.dumps(mcp_block["dvad"], indent=2) + "\n"
            )
        mcp_block["dvad"] = entry
        proj["mcpServers"] = mcp_block
        projects[project_key] = proj
        updated["projects"] = projects

    serialized = json.dumps(updated, indent=2) + "\n"

    print(f"→ config: {claude_json}")
    print(f"→ scope:  {scope}")
    print(f"→ binary: {entry['command']}")
    print(f"→ skill:  {intended_skill}")
    if dry_run:
        print("\n--- DRY RUN ---\n")
        print(f"{claude_json.name} would become:")
        print(serialized)
        print("\n---\n")
        print(f"skill file {intended_skill} would contain ~{len(_embedded_skill_body())} bytes of skill content.")
        return 0

    # 1. Write .claude.json (with backup).
    try:
        claude_json.parent.mkdir(parents=True, exist_ok=True)
        if claude_json.exists():
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = claude_json.with_name(f"{claude_json.name}.dvad-backup.{stamp}")
            shutil.copy2(claude_json, backup)
            print(f"✓ backup: {backup}")
        claude_json.write_text(serialized, encoding="utf-8")
        try:
            os.chmod(claude_json, 0o600)
        except OSError:
            pass
        print(f"✓ wrote {claude_json}")
    except OSError as exc:
        sys.stderr.write(f"could not write {claude_json}: {exc}\n")
        _print_paste_fallback(claude_json, serialized, intended_skill)
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
        _print_paste_fallback(claude_json, serialized, intended_skill)
        return 1

    print("\nInstall complete. Restart your Claude Code session and run dvad_config.")
    return 0


def _print_paste_fallback(config_file: Path, serialized: str, skill_path: Path) -> None:
    print("\n--- PASTE FALLBACK ---\n", file=sys.stderr)
    print(
        f"Copy the JSON below into {config_file}:\n\n{serialized}\n",
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

## Handoff format — MANDATORY

When presenting dvad results to the human, you MUST use the format below. Do NOT summarize, rewrite, or flatten dvad findings into your own analysis. The human needs to see that these findings came from independent adversarial review, not from you.

### Header (always include)

```
--- dvad adversarial review ---
Models: {list all models from models_used, e.g. gemini-3-flash, gpt-5.4-mini, gemini-2.5-flash, gpt-5.2}
Providers: {count distinct providers, e.g. "2 providers (Google, OpenAI)"}
Outcome: {outcome} | Duration: {duration_seconds}s | Cost: ${cost_usd}
```

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
"""
