#!/usr/bin/env python3
"""Verify each model in its assigned role produces valid output.

No timeouts, no deadlines — just confirm each model can do its job
when given all the time it needs. Run with all three provider keys set.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dvad_agent import config, prompts, cost
from dvad_agent.providers import call_with_retry, parse_and_validate_findings, ProviderResult

import httpx


ARTIFACT_PATH = os.path.expanduser(
    "~/Desktop/Board Foot Android App/boardfoot.sample.plan.md"
)


async def test_reviewer(client: httpx.AsyncClient, model, artifact: str):
    """Send the real reviewer prompt to a model, validate the response."""
    reviewer_prompt = prompts.build_reviewer_user_prompt(artifact, "plan", None, None)
    system = prompts.REVIEWER_SYSTEM

    print(f"\n{'='*60}")
    print(f"REVIEWER: {model.name} ({model.provider})")
    print(f"{'='*60}")

    t0 = time.monotonic()
    try:
        result = await call_with_retry(
            client, model, system, reviewer_prompt,
            max_output_tokens=model.max_output_tokens,
            max_retries=1,
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"  FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        return False

    elapsed = time.monotonic() - t0
    print(f"  Response in {elapsed:.1f}s")
    print(f"  Tokens: {result.input_tokens} in / {result.output_tokens} out")

    findings, err = parse_and_validate_findings(result.text, model.name, model.provider)
    if err:
        print(f"  PARSE/SCHEMA FAILED: {err.error_type.value} — {err.message}")
        print(f"  Raw (first 300 chars): {result.text[:300]}")
        return False

    print(f"  Valid findings: {len(findings)}")
    for f in findings[:3]:
        print(f"    [{f['severity']}] {f['issue'][:80]}")
    if len(findings) > 3:
        print(f"    ... and {len(findings) - 3} more")

    c = cost.estimate_cost(model, result.input_tokens, result.output_tokens)
    if c is not None:
        print(f"  Cost: ${c:.4f}")
    return True


async def test_dedup(client: httpx.AsyncClient, model, sample_findings: list[dict]):
    """Send the real dedup prompt to a model, validate the response."""
    user_prompt = prompts.build_dedup_user_prompt(sample_findings)
    system = prompts.DEDUP_SYSTEM

    print(f"\n{'='*60}")
    print(f"DEDUP: {model.name} ({model.provider})")
    print(f"{'='*60}")

    t0 = time.monotonic()
    try:
        result = await call_with_retry(
            client, model, system, user_prompt,
            max_output_tokens=model.max_output_tokens,
            max_retries=1,
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"  FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        return False

    elapsed = time.monotonic() - t0
    print(f"  Response in {elapsed:.1f}s")
    print(f"  Tokens: {result.input_tokens} in / {result.output_tokens} out")

    findings, err = parse_and_validate_findings(result.text, model.name, model.provider)
    if err:
        print(f"  PARSE/SCHEMA FAILED: {err.error_type.value} — {err.message}")
        print(f"  Raw (first 500 chars): {result.text[:500]}")
        return False

    print(f"  Deduped findings: {len(findings)}")
    for f in findings[:3]:
        print(f"    [{f['severity']}] {f['issue'][:80]}")
    if len(findings) > 3:
        print(f"    ... and {len(findings) - 3} more")
    return True


async def main():
    config.setup_logging("WARNING")  # quiet httpx noise

    with open(ARTIFACT_PATH) as f:
        artifact = f.read()

    providers = config.detect_providers()
    print(f"Detected providers: {', '.join(sorted(providers.keys()))}")
    if not providers:
        print("No API keys found in environment. Set ANTHROPIC/OPENAI/GOOGLE keys.")
        return

    reviewers, dedup_models = config.build_model_table(providers)
    print(f"Reviewers: {[m.name for m in reviewers]}")
    print(f"Dedup models: {[m.name for m in dedup_models]}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Test all reviewers in parallel — don't wait behind a slow provider
        import asyncio as _aio

        reviewer_results = {}
        reviewer_tasks = {
            _aio.create_task(test_reviewer(client, model, artifact)): model
            for model in reviewers
        }
        done, _ = await _aio.wait(reviewer_tasks.keys(), timeout=180.0)
        for task in done:
            model = reviewer_tasks[task]
            try:
                reviewer_results[model.name] = task.result()
            except Exception as exc:
                print(f"\n  {model.name}: EXCEPTION — {exc}")
                reviewer_results[model.name] = False
        for task in reviewer_tasks:
            if not task.done():
                model = reviewer_tasks[task]
                print(f"\n  {model.name}: TIMED OUT after 180s")
                reviewer_results[model.name] = False
                task.cancel()

        # Build sample findings for dedup testing from the first successful reviewer
        sample_findings = [
            {"reviewer": "model-a", "severity": "high", "category": "correctness",
             "issue": "Floating point precision errors in financial calculations",
             "detail": "Using Double for currency math introduces rounding errors."},
            {"reviewer": "model-a", "severity": "medium", "category": "reliability",
             "issue": "State loss on screen rotation",
             "detail": "No ViewModel or onSaveInstanceState means data is lost."},
            {"reviewer": "model-b", "severity": "high", "category": "correctness",
             "issue": "Financial calculations use floating-point arithmetic prone to rounding errors",
             "detail": "BigDecimal should be used instead of Double for monetary values."},
            {"reviewer": "model-b", "severity": "medium", "category": "testing",
             "issue": "No automated tests for core business logic",
             "detail": "Manual testing only; no unit or integration tests planned."},
            {"reviewer": "model-c", "severity": "high", "category": "correctness",
             "issue": "Board-foot formula has floating point precision issues",
             "detail": "Accumulated rounding across multiple entries creates drift."},
            {"reviewer": "model-c", "severity": "low", "category": "maintainability",
             "issue": "All logic in MainActivity creates poor separation of concerns",
             "detail": "No dedicated calculator or state management class."},
        ]

        # Test all dedup models in parallel
        dedup_results = {}
        dedup_tasks = {
            _aio.create_task(test_dedup(client, model, sample_findings)): model
            for model in dedup_models
        }
        done, _ = await _aio.wait(dedup_tasks.keys(), timeout=120.0)
        for task in done:
            model = dedup_tasks[task]
            try:
                dedup_results[model.name] = task.result()
            except Exception as exc:
                print(f"\n  {model.name}: EXCEPTION — {exc}")
                dedup_results[model.name] = False
        for task in dedup_tasks:
            if not task.done():
                model = dedup_tasks[task]
                print(f"\n  {model.name}: TIMED OUT after 120s")
                dedup_results[model.name] = False
                task.cancel()

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print("\nReviewers:")
    for name, ok in reviewer_results.items():
        print(f"  {'PASS' if ok else 'FAIL'} — {name}")
    print("\nDedup:")
    for name, ok in dedup_results.items():
        print(f"  {'PASS' if ok else 'FAIL'} — {name}")

    all_ok = all(reviewer_results.values()) and all(dedup_results.values())
    print(f"\nOverall: {'ALL PASS' if all_ok else 'FAILURES DETECTED'}")


if __name__ == "__main__":
    asyncio.run(main())
