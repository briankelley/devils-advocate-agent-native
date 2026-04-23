import asyncio
import json
from pathlib import Path

import pytest

from dvad_agent import config as _config
from dvad_agent.budget import BudgetCorrupted, BudgetManager, _state_root, _today_str


pytestmark = pytest.mark.asyncio


async def test_read_status_initial_zero():
    bm = BudgetManager()
    status = await bm.read_status()
    assert status.spent_usd == 0.0
    assert status.warning_level.value == "none"


async def test_record_spend_accumulates():
    bm = BudgetManager()
    await bm.record_spend(0.5)
    await bm.record_spend(0.25)
    status = await bm.read_status()
    assert status.spent_usd == pytest.approx(0.75)


async def test_budget_file_permissions():
    bm = BudgetManager()
    await bm.record_spend(0.1)
    p = _state_root() / f"{_today_str()}.json"
    assert p.exists()
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600


async def test_would_exceed(monkeypatch):
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "1.00")
    bm = BudgetManager()
    await bm.record_spend(0.9)
    blocked, status = await bm.would_exceed(0.2)
    assert blocked is True
    blocked, _ = await bm.would_exceed(0.05)
    assert blocked is False


async def test_daily_cap_disabled_never_blocks(monkeypatch):
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "0")
    bm = BudgetManager()
    blocked, _ = await bm.would_exceed(1_000_000)
    assert blocked is False


async def test_corrupted_file_fails_closed():
    root = _state_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{_today_str()}.json").write_text("{not_valid_json", encoding="utf-8")
    bm = BudgetManager()
    with pytest.raises(BudgetCorrupted):
        await bm.read_status()


async def test_warning_thresholds(monkeypatch):
    monkeypatch.setenv("DVAD_BUDGET_DAILY", "10.00")
    bm = BudgetManager()
    await bm.record_spend(7.1)  # 71%
    status = await bm.read_status()
    assert status.warning_level.value == "soft"
    await bm.record_spend(1.5)  # 86%
    status = await bm.read_status()
    assert status.warning_level.value == "hard"
