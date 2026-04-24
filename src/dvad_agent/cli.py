"""Developer testing surface — explicitly NOT the product.

Subcommands provide phase-gate verification during the build and ongoing
debugging: config, budget, probe, scan, review, install.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

from . import __version__, config as _config
from . import review as _review
from . import secrets as _secrets
from .budget import BudgetManager
from .providers import call_with_retry
from .types import ModelConfig, ReviewContext


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=_json_default))


def _json_default(obj: object) -> object:
    if hasattr(obj, "value"):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return str(obj)


# ─── config ───────────────────────────────────────────────────────────────────


def cmd_config(_args: argparse.Namespace) -> int:
    _config.setup_logging()
    snap = _config.config_snapshot()
    _print_json(snap)
    return 0


# ─── budget ───────────────────────────────────────────────────────────────────


def cmd_budget(_args: argparse.Namespace) -> int:
    _config.setup_logging()

    async def _run() -> dict:
        bm = BudgetManager()
        status = await bm.read_status()
        return {
            "spent_usd": status.spent_usd,
            "cap_usd": status.cap_usd,
            "remaining_usd": status.remaining_usd,
            "warning_level": status.warning_level.value,
            "day": status.day,
        }

    _print_json(asyncio.run(_run()))
    return 0


# ─── probe ────────────────────────────────────────────────────────────────────


def cmd_probe(args: argparse.Namespace) -> int:
    _config.setup_logging()
    reviewers, dedup = _config.build_model_table()
    pool: list[ModelConfig] = list(reviewers) + list(dedup)
    target = next((m for m in pool if m.model_id == args.model), None)
    if target is None:
        sys.stderr.write(
            f"model '{args.model}' is not currently detected. "
            f"Available: {', '.join(m.model_id for m in pool)}\n"
        )
        return 2

    async def _run() -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            result = await call_with_retry(
                client, target,
                system_prompt='Return STRICT JSON: {"ok": true, "echo": "<input>"}',
                user_prompt="ping",
                max_output_tokens=100,
            )
        return {
            "model": target.model_id,
            "provider": target.provider,
            "text": result.text[:500],
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        }

    try:
        _print_json(asyncio.run(_run()))
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"probe failed: {type(exc).__name__}: {exc}\n")
        return 1


# ─── scan ─────────────────────────────────────────────────────────────────────


def cmd_scan(args: argparse.Namespace) -> int:
    _config.setup_logging()
    try:
        content = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"cannot read {args.file}: {exc}\n")
        return 2
    matches = _secrets.scan(content, channel=f"file:{args.file}")
    _print_json(
        {
            "file": args.file,
            "matches": [
                {
                    "pattern_type": m.pattern_type,
                    "approx_line_range": list(m.approx_line_range),
                    "channel": m.channel,
                }
                for m in matches
            ],
        }
    )
    return 0


# ─── review ───────────────────────────────────────────────────────────────────


def cmd_review(args: argparse.Namespace) -> int:
    _config.setup_logging()
    try:
        artifact = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"cannot read {args.file}: {exc}\n")
        return 2

    context = ReviewContext(
        project_name=args.project,
        repo_root=args.repo_root,
        reference_files=list(args.ref or []),
        instructions=args.instructions,
    )

    def _progress(event: dict) -> None:
        sys.stderr.write(f"[progress] {json.dumps(event)}\n")

    async def _run() -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            bm = BudgetManager()
            resp = await _review.run_lite_review(
                client,
                artifact=artifact,
                artifact_type=args.artifact_type,
                context=context,
                budget_limit=args.budget_limit,
                parent_review_id=args.parent_review_id,
                budget_manager=bm,
                progress=_progress,
            )
            return resp.to_dict()

    result = asyncio.run(_run())
    if args.markdown and result.get("status") == "ok":
        print(result.get("report_markdown", ""))
    else:
        _print_json(result)
    return 0 if result.get("status") in ("ok",) else 1


# ─── install ──────────────────────────────────────────────────────────────────


def cmd_install(args: argparse.Namespace) -> int:
    from .install import run_install

    return run_install(dry_run=args.dry_run, config_path=args.config, skill_dir=args.skill_dir, scope=args.scope)


# ─── argparse ─────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dvad-agent",
        description="Developer utilities for dvad-agent-native. The MCP server is the product; this CLI is scaffolding.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("config", help="Report detected providers + default models.")
    p_config.set_defaults(func=cmd_config)

    p_budget = sub.add_parser("budget", help="Show today's spend and daily cap.")
    p_budget.set_defaults(func=cmd_budget)

    p_probe = sub.add_parser("probe", help="Send a trivial ping to a specific model.")
    p_probe.add_argument("--model", required=True)
    p_probe.set_defaults(func=cmd_probe)

    p_scan = sub.add_parser("scan", help="Run the secrets pre-scanner over a local file.")
    p_scan.add_argument("--file", required=True)
    p_scan.set_defaults(func=cmd_scan)

    p_review = sub.add_parser("review", help="Run a full lite-mode review from the CLI.")
    p_review.add_argument("--file", required=True)
    p_review.add_argument(
        "--artifact-type",
        default="plan",
        choices=["plan", "spec", "diff", "code", "decision", "test"],
    )
    p_review.add_argument("--project", default=None)
    p_review.add_argument("--repo-root", default=None)
    p_review.add_argument("--ref", action="append", help="Reference file relative path (repeatable).")
    p_review.add_argument("--instructions", default=None)
    p_review.add_argument("--budget-limit", type=float, default=None)
    p_review.add_argument("--parent-review-id", default=None)
    p_review.add_argument("--markdown", action="store_true", help="Print markdown report instead of JSON.")
    p_review.set_defaults(func=cmd_review)

    p_install = sub.add_parser("install", help="Register the MCP server with Claude Code.")
    p_install.add_argument("--dry-run", action="store_true")
    p_install.add_argument(
        "--config",
        default=None,
        help="Path to .claude.json (default: ~/.claude.json).",
    )
    p_install.add_argument(
        "--skill-dir",
        default=None,
        help="Path to Claude Code skill directory (default: ~/.claude/skills/).",
    )
    p_install.add_argument(
        "--scope",
        choices=["user", "local"],
        default="user",
        help="Install scope: 'user' (all projects) or 'local' (current directory only). Default: user.",
    )
    p_install.set_defaults(func=cmd_install)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
