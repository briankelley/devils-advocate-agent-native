"""MCP stdio server exposing dvad_review, dvad_estimate, dvad_config.

All tool returns carry the ``status`` discriminator (ToolResponse). The server
is intentionally thin: it builds ReviewContext, owns the httpx lifespan, and
forwards progress notifications back to the MCP client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

import httpx

from . import config as _config
from . import cost as _cost
from . import review as _review
from .budget import BudgetManager
from .types import ReviewContext, ToolResponse


log = logging.getLogger("dvad_agent.server")


# ─── Tool schemas ─────────────────────────────────────────────────────────────


DVAD_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact": {
            "type": "string",
            "description": "The text content to review (plan, spec, diff, code, decision, or test).",
        },
        "artifact_type": {
            "type": "string",
            "enum": ["plan", "spec", "diff", "code", "decision", "test"],
            "default": "plan",
        },
        "mode": {
            "type": "string",
            "enum": ["lite"],
            "default": "lite",
            "description": "Only 'lite' mode is supported in v1.",
        },
        "context": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "repo_root": {
                    "type": "string",
                    "description": "Absolute repo root. Required when reference_files is provided.",
                },
                "reference_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relative paths beneath repo_root. Size caps enforced (1 MiB per file, 5 MiB total).",
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional extra instructions for reviewers.",
                },
            },
        },
        "parent_review_id": {"type": "string"},
        "budget_limit": {"type": "number", "description": "Per-call USD cap override."},
    },
    "required": ["artifact"],
}

DVAD_ESTIMATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact": {"type": "string"},
        "artifact_type": {
            "type": "string",
            "enum": ["plan", "spec", "diff", "code", "decision", "test"],
            "default": "plan",
        },
        "context": DVAD_REVIEW_SCHEMA["properties"]["context"],
    },
    "required": ["artifact"],
}

DVAD_CONFIG_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


# ─── Tool handlers ────────────────────────────────────────────────────────────


async def handle_dvad_review(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    budget_manager: BudgetManager,
    progress_cb,
) -> dict[str, Any]:
    artifact = payload.get("artifact", "")
    artifact_type = payload.get("artifact_type", "plan")
    mode = payload.get("mode", "lite")
    if mode != "lite":
        return ToolResponse(
            status="invalid_request",
            body={"reason": f"mode={mode} not supported in v1; only 'lite'."},
        ).to_dict()
    ctx_raw = payload.get("context") or {}
    if not isinstance(ctx_raw, dict):
        return ToolResponse(
            status="invalid_request",
            body={"reason": "context must be an object"},
        ).to_dict()
    context = ReviewContext(
        project_name=ctx_raw.get("project_name"),
        repo_root=ctx_raw.get("repo_root"),
        reference_files=list(ctx_raw.get("reference_files") or []),
        instructions=ctx_raw.get("instructions"),
    )
    parent_id = payload.get("parent_review_id")
    budget_limit = payload.get("budget_limit")

    if not isinstance(artifact, str) or not artifact.strip():
        return ToolResponse(
            status="invalid_request",
            body={"reason": "artifact must be a non-empty string"},
        ).to_dict()

    resp = await _review.run_lite_review(
        client,
        artifact=artifact,
        artifact_type=artifact_type,
        context=context,
        budget_limit=budget_limit,
        parent_review_id=parent_id,
        budget_manager=budget_manager,
        progress=progress_cb,
    )
    return resp.to_dict()


async def handle_dvad_estimate(
    payload: dict[str, Any],
    budget_manager: BudgetManager,
) -> dict[str, Any]:
    artifact = payload.get("artifact", "")
    artifact_type = payload.get("artifact_type", "plan")
    if not isinstance(artifact, str) or not artifact.strip():
        return {
            "status": "invalid_request",
            "reason": "artifact must be a non-empty string",
        }

    reviewers, dedup_models = _config.build_model_table()
    in_tokens = _cost.estimate_tokens(artifact)
    per_model: list[dict[str, Any]] = []
    any_unknown = False
    total_estimate = 0.0
    for m in reviewers:
        fits, est, limit = _cost.check_context_window(m, artifact)
        c = _cost.estimate_cost(m, in_tokens, m.max_output_tokens)
        if c is None:
            any_unknown = True
        else:
            total_estimate += c
        per_model.append(
            {
                "model": m.model_id,
                "provider": m.provider,
                "estimated_tokens_in": est,
                "estimated_tokens_out": m.max_output_tokens,
                "estimated_cost_usd": c,
                "context_window_fits": fits,
                "context_window_limit": limit,
            }
        )
    dedup_estimate: dict[str, Any] | None = None
    if dedup_models:
        m = dedup_models[0]
        in_est = 6 * 100 * len(reviewers)
        out_est = 500
        c = _cost.estimate_cost(m, in_est, out_est)
        if c is None:
            any_unknown = True
        else:
            total_estimate += c
        dedup_estimate = {
            "model": m.model_id,
            "provider": m.provider,
            "estimated_tokens_in": in_est,
            "estimated_tokens_out": out_est,
            "estimated_cost_usd": c,
            "approximation_note": (
                "Heuristic: 6 findings × ~100 tokens per reviewer, "
                "~500 tokens output."
            ),
        }

    total_tokens_in = sum(m.get("estimated_tokens_in", 0) for m in per_model)
    total_tokens_out = sum(m.get("estimated_tokens_out", 0) for m in per_model)
    if dedup_estimate:
        total_tokens_in += dedup_estimate.get("estimated_tokens_in", 0)
        total_tokens_out += dedup_estimate.get("estimated_tokens_out", 0)

    status = await budget_manager.read_status()
    return {
        "status": "ok",
        "artifact_type": artifact_type,
        "reviewers": per_model,
        "dedup": dedup_estimate,
        "total_estimated_cost_usd": total_estimate,
        "total_estimated_tokens": total_tokens_in + total_tokens_out,
        "total_estimated_tokens_in": total_tokens_in,
        "total_estimated_tokens_out": total_tokens_out,
        "total_estimated_tokens_note": (
            "Approximation: token estimates are based on artifact size only. "
            "Actual dvad_review input includes system prompts, rubrics, and "
            "reference files, so real token consumption is typically higher."
        ),
        "pricing_unavailable": any_unknown,
        "budget_status": {
            "spent_usd": status.spent_usd,
            "cap_usd": status.cap_usd,
            "remaining_usd": status.remaining_usd,
            "warning_level": status.warning_level.value,
            "day": status.day,
        },
    }


async def handle_dvad_config(budget_manager: BudgetManager) -> dict[str, Any]:
    snap = _config.config_snapshot()
    status = await budget_manager.read_status()
    snap["budget_status"] = {
        "spent_usd": status.spent_usd,
        "cap_usd": status.cap_usd,
        "remaining_usd": status.remaining_usd,
        "warning_level": status.warning_level.value,
        "day": status.day,
    }
    snap["status"] = "ok"
    return snap


# ─── Server runner ────────────────────────────────────────────────────────────


async def _serve() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types as mcp_types

    _config.setup_logging()
    # Harden file permissions
    try:
        os.umask(0o077)
    except OSError:
        pass

    budget_manager = BudgetManager()
    # Single shared httpx client for the server's lifetime
    client = httpx.AsyncClient(timeout=60)
    inflight: set[asyncio.Task] = set()

    app = Server("dvad-agent-native")

    @app.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="dvad_review",
                description=(
                    "Run an adversarial multi-LLM review of an artifact. "
                    "Returns structured findings + markdown handoff."
                ),
                inputSchema=DVAD_REVIEW_SCHEMA,
            ),
            mcp_types.Tool(
                name="dvad_estimate",
                description="Estimate the cost of reviewing an artifact, without making any external calls.",
                inputSchema=DVAD_ESTIMATE_SCHEMA,
            ),
            mcp_types.Tool(
                name="dvad_config",
                description="Report detected providers, default models, budget, and platform.",
                inputSchema=DVAD_CONFIG_SCHEMA,
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None):
        arguments = arguments or {}

        def _progress(event: dict[str, Any]) -> None:
            # We keep progress in-process — MCP progress notifications require
            # the client to have issued a progress token. If present, a client
            # would wire this through the session; for v1 we just log.
            log.info("progress: %s", event)

        try:
            if name == "dvad_review":
                task = asyncio.current_task()
                if task is not None:
                    inflight.add(task)
                try:
                    result = await handle_dvad_review(
                        client, arguments, budget_manager, _progress
                    )
                finally:
                    if task is not None:
                        inflight.discard(task)
            elif name == "dvad_estimate":
                result = await handle_dvad_estimate(arguments, budget_manager)
            elif name == "dvad_config":
                result = await handle_dvad_config(budget_manager)
            else:
                result = {"status": "invalid_request", "reason": f"unknown tool: {name}"}
        except Exception as exc:  # noqa: BLE001
            log.exception("Tool %s crashed", name)
            result = {
                "status": "invalid_request",
                "reason": f"internal error: {type(exc).__name__}: {exc}",
            }
        return [mcp_types.TextContent(type="text", text=json.dumps(result))]

    async def _shutdown(reason: str) -> None:
        log.info("shutdown: %s", reason)
        # 1. stop accepting new tool calls: the mcp server runtime handles this
        # 2. drain in-flight reviews, bounded
        if inflight:
            done, pending = await asyncio.wait(list(inflight), timeout=10)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler(signum: int, _frame) -> None:  # noqa: ANN001
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            signal.signal(sig, _signal_handler)

    try:
        async with stdio_server() as (read, write):
            server_task = asyncio.create_task(app.run(read, write, app.create_initialization_options()))
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, pending = await asyncio.wait(
                [server_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done and not server_task.done():
                server_task.cancel()
                try:
                    await server_task
                except (asyncio.CancelledError, Exception):
                    pass
    except BrokenPipeError:
        log.warning("stdio broken pipe; parent died mid-review")
    finally:
        await _shutdown("normal")


def main() -> int:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"dvad-agent-mcp startup/runtime failure: {exc}\n")
        return 1
    return 0
