"""Provider HTTP adapters (httpx direct — no vendor SDKs).

Three families: Anthropic Messages API, OpenAI /chat/completions (plus
OpenAI-compat endpoints like Gemini's, OpenRouter, Groq, vLLM), and OpenAI
/v1/responses (gpt-5, o3 reasoning series).

The dispatcher preserves provider identity for diversity/degraded computation
even when transport is OpenAI-compatible (e.g. Google via compat endpoint).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .types import ModelConfig, ReviewerError, ReviewerErrorType


log = logging.getLogger("dvad_agent.providers")


ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_RETRIES = 3
_529_MAX_RETRIES = 3
_529_BUDGET_SECONDS = 30.0


# ─── Call result ──────────────────────────────────────────────────────────────


@dataclass
class ProviderResult:
    text: str
    input_tokens: int
    output_tokens: int


# ─── Anthropic ────────────────────────────────────────────────────────────────


async def call_anthropic(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> ProviderResult:
    url = f"{model.api_base.rstrip('/')}/v1/messages"
    headers = {
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
        "x-api-key": model.api_key,
    }
    body: dict[str, Any] = {
        "model": model.model_id,
        "max_tokens": max_output_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if system_prompt:
        body["system"] = system_prompt
    if not model.thinking_enabled:
        # Explicitly disable extended thinking; absence of key is NOT equivalent
        # on 4-6+ models which may default to adaptive.
        body["thinking"] = {"type": "disabled"}

    resp = await client.post(url, json=body, headers=headers, timeout=model.timeout)
    resp.raise_for_status()
    data = resp.json()
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    usage = data.get("usage", {})
    return ProviderResult(
        text=text,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )


# ─── OpenAI chat-completions compatible ───────────────────────────────────────


async def call_openai_compatible(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> ProviderResult:
    url = f"{model.api_base.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model.api_key}",
    }
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    body: dict[str, Any] = {
        "model": model.model_id,
        "messages": messages,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }

    resp = await client.post(url, json=body, headers=headers, timeout=model.timeout)
    resp.raise_for_status()
    data = resp.json()
    text = ""
    choices = data.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
    usage = data.get("usage") or {}
    return ProviderResult(
        text=text,
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
    )


# ─── OpenAI /v1/responses ─────────────────────────────────────────────────────


async def call_openai_responses(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> ProviderResult:
    url = f"{model.api_base.rstrip('/')}/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model.api_key}",
    }
    input_messages: list[dict[str, str]] = []
    if system_prompt:
        input_messages.append({"role": "system", "content": system_prompt})
    input_messages.append({"role": "user", "content": user_prompt})

    body: dict[str, Any] = {
        "model": model.model_id,
        "input": input_messages,
        "max_output_tokens": max_output_tokens,
        # Responses API puts format inside `text`, not top-level `response_format`.
        "text": {"format": {"type": "json_object"}},
    }

    resp = await client.post(url, json=body, headers=headers, timeout=model.timeout)
    resp.raise_for_status()
    data = resp.json()
    text = ""
    for block in data.get("output", []):
        for part in block.get("content", []):
            if part.get("type") == "output_text":
                text += part.get("text", "")
    # Fallback for alternate shape
    if not text and data.get("output_text"):
        text = data["output_text"]
    usage = data.get("usage") or {}
    return ProviderResult(
        text=text,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )


# ─── Google Gemini native (v1beta generateContent) ────────────────────────────


async def call_google(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> ProviderResult:
    """Native Gemini path. Used when OpenAI-compat evaluation fails for Google."""
    url = (
        f"{model.api_base.rstrip('/')}/v1beta/models/{model.model_id}:generateContent"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": model.api_key,
    }
    generation_config: dict[str, Any] = {
        "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json",
    }
    if not model.thinking_enabled:
        # Gemini 2.5 series defaults thinking ON, which silently consumes the
        # output token budget before any visible content. Pin to 0 for
        # non-reasoning usage (reviewer + dedup roles in v1).
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": generation_config,
    }
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    resp = await client.post(url, json=body, headers=headers, timeout=model.timeout)
    resp.raise_for_status()
    data = resp.json()
    text = ""
    for cand in data.get("candidates", []):
        content = cand.get("content") or {}
        for part in content.get("parts", []):
            if "text" in part:
                text += part["text"]
    usage_meta = data.get("usageMetadata") or {}
    return ProviderResult(
        text=text,
        input_tokens=int(usage_meta.get("promptTokenCount", 0)),
        output_tokens=int(usage_meta.get("candidatesTokenCount", 0)),
    )


# ─── Dispatcher ───────────────────────────────────────────────────────────────


async def call_model(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int | None = None,
) -> ProviderResult:
    """Route to the right provider function.

    Dispatch order:
      1. ``use_responses_api`` → OpenAI Responses
      2. ``use_openai_compat`` → OpenAI-compatible transport (e.g. Gemini compat)
      3. provider-native function
    """
    max_out = max_output_tokens or model.max_output_tokens
    if model.use_responses_api:
        return await call_openai_responses(client, model, system_prompt, user_prompt, max_out)
    if model.use_openai_compat:
        return await call_openai_compatible(client, model, system_prompt, user_prompt, max_out)
    if model.provider == "anthropic":
        return await call_anthropic(client, model, system_prompt, user_prompt, max_out)
    if model.provider == "openai":
        return await call_openai_compatible(client, model, system_prompt, user_prompt, max_out)
    if model.provider == "google":
        return await call_google(client, model, system_prompt, user_prompt, max_out)
    # Unknown provider — assume OpenAI-compatible transport.
    return await call_openai_compatible(client, model, system_prompt, user_prompt, max_out)


# ─── Retry engine ─────────────────────────────────────────────────────────────


async def call_with_retry(
    client: httpx.AsyncClient,
    model: ModelConfig,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> ProviderResult:
    """Exponential backoff with jitter. 529-specific budget up to ~30s."""
    last_exc: Exception | None = None
    elapsed_529 = 0.0
    attempts_529 = 0
    for attempt in range(max_retries + 1):
        try:
            return await call_model(client, model, system_prompt, user_prompt, max_output_tokens)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status == 529:
                attempts_529 += 1
                retry_after = float(exc.response.headers.get("retry-after", 0) or 0)
                wait = max(retry_after, (4 ** (attempt + 1) / 4) + random.random())
                remaining = _529_BUDGET_SECONDS - elapsed_529
                if wait > remaining or attempts_529 > _529_MAX_RETRIES:
                    raise
                log.warning("%s: 529 overloaded, waiting %.1fs", model.name, wait)
                t0 = time.monotonic()
                await asyncio.sleep(wait)
                elapsed_529 += time.monotonic() - t0
                continue
            if status == 429:
                retry_after = float(exc.response.headers.get("retry-after", 0) or 0)
                wait = max(retry_after, (2 ** attempt) + random.random())
            elif status >= 500:
                wait = (2 ** attempt) + random.random()
            else:
                raise
            log.warning(
                "%s: HTTP %d, retry %d/%d in %.1fs",
                model.name, status, attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            wait = (2 ** attempt) + random.random()
            log.warning(
                "%s: %s, retry %d/%d in %.1fs",
                model.name, type(exc).__name__, attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{model.name}: unreachable retry state")  # pragma: no cover


# ─── JSON parsing / schema validation ─────────────────────────────────────────


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def sanitize_json_output(raw: str) -> str:
    """Strip code fences or extract the first JSON block."""
    raw = raw.strip()
    if raw.startswith("{") or raw.startswith("["):
        return raw
    m = _JSON_FENCE.search(raw)
    if m:
        return m.group(1).strip()
    # Fallback: find the first balanced object.
    start = raw.find("{")
    if start == -1:
        return raw
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return raw[start:]


def parse_and_validate_findings(
    raw: str,
    model_name: str,
    provider: str,
) -> tuple[list[dict] | None, ReviewerError | None]:
    """Parse reviewer JSON and validate the findings schema.

    Returns ``(findings, None)`` on success; ``(None, ReviewerError)`` on any
    failure path. Every failure preserves ``raw_response`` for debugging.
    """
    cleaned = sanitize_json_output(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=ReviewerErrorType.PARSE_FAILURE,
            message=f"JSON parse failed: {exc}",
            raw_response=raw,
        )

    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        return None, ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=ReviewerErrorType.SCHEMA_INVALID,
            message="Root is not an object with a findings array",
            raw_response=raw,
        )

    out: list[dict] = []
    for i, item in enumerate(parsed["findings"]):
        if not isinstance(item, dict):
            return None, ReviewerError(
                model_name=model_name,
                provider=provider,
                error_type=ReviewerErrorType.SCHEMA_INVALID,
                message=f"findings[{i}] is not an object",
                raw_response=raw,
            )
        severity = item.get("severity")
        category = item.get("category")
        issue = item.get("issue")
        if not isinstance(severity, str) or not isinstance(category, str) or not isinstance(issue, str) or not issue.strip():
            return None, ReviewerError(
                model_name=model_name,
                provider=provider,
                error_type=ReviewerErrorType.SCHEMA_INVALID,
                message=f"findings[{i}] missing required fields",
                raw_response=raw,
            )
        out.append(
            {
                "severity": severity,
                "category": category,
                "issue": issue,
                "detail": item.get("detail", "") or "",
            }
        )
    return out, None


def map_http_to_reviewer_error(
    exc: Exception, model_name: str, provider: str
) -> ReviewerError:
    """Convert an HTTP/httpx exception into a ReviewerError with the right type."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (408, 504):
            etype = ReviewerErrorType.TIMEOUT
        elif status == 429:
            etype = ReviewerErrorType.RATE_LIMIT
        elif status >= 500:
            etype = ReviewerErrorType.SERVER_ERROR
        else:
            etype = ReviewerErrorType.SERVER_ERROR
        return ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=etype,
            message=f"HTTP {status}: {exc.response.text[:200]}",
        )
    if isinstance(exc, httpx.TimeoutException):
        return ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=ReviewerErrorType.TIMEOUT,
            message=str(exc),
        )
    if isinstance(exc, httpx.ConnectError):
        return ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=ReviewerErrorType.CONNECTION_ERROR,
            message=str(exc),
        )
    if isinstance(exc, asyncio.CancelledError):
        return ReviewerError(
            model_name=model_name,
            provider=provider,
            error_type=ReviewerErrorType.DEADLINE_EXCEEDED,
            message="cancelled",
        )
    return ReviewerError(
        model_name=model_name,
        provider=provider,
        error_type=ReviewerErrorType.SERVER_ERROR,
        message=f"{type(exc).__name__}: {exc}",
    )
