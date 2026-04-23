"""Daily spend bookkeeping with two-layer locking.

- asyncio.Lock for in-process coroutine safety
- fcntl.flock via asyncio.to_thread for cross-process safety

Calendar day in local time. ``DVAD_BUDGET_DAILY=0`` disables the cap but
continues tracking spend. Corrupted file → fail closed. Missing file → initialize.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import fcntl
import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from . import config as _config
from .types import BudgetStatus, WarningLevel


log = logging.getLogger("dvad_agent.budget")


BUDGET_SUBDIR = "devils-advocate-agent/budget"
SOFT_WARNING_THRESHOLD = 0.70
HARD_WARNING_THRESHOLD = 0.85


class BudgetCorrupted(Exception):
    """Today's budget file exists but failed JSON parse / schema check."""


@dataclass
class _PersistedDay:
    day: str
    spent_usd: float

    @staticmethod
    def from_dict(data: dict) -> "_PersistedDay":
        if not isinstance(data, dict):
            raise BudgetCorrupted("budget file root is not an object")
        day = data.get("day")
        spent = data.get("spent_usd")
        if not isinstance(day, str) or not isinstance(spent, (int, float)):
            raise BudgetCorrupted("budget file missing required fields")
        return _PersistedDay(day=day, spent_usd=float(spent))

    def to_dict(self) -> dict:
        return {"day": self.day, "spent_usd": self.spent_usd}


def _state_root() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / BUDGET_SUBDIR


def _today_str() -> str:
    return dt.date.today().isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if current_mode & 0o077:
            # too permissive — tighten + warn
            log.warning(
                "Budget dir %s permissions %o are more permissive than 0700; tightening",
                path, current_mode,
            )
            os.chmod(path, 0o700)
    except OSError as exc:  # noqa: BLE001
        log.warning("Could not verify/chmod budget dir %s: %s", path, exc)


def _path_for(day: str) -> Path:
    return _state_root() / f"{day}.json"


def _compute_warning_level(spent: float, cap: float) -> WarningLevel:
    if cap <= 0:
        return WarningLevel.NONE
    pct = spent / cap
    if pct >= HARD_WARNING_THRESHOLD:
        return WarningLevel.HARD
    if pct >= SOFT_WARNING_THRESHOLD:
        return WarningLevel.SOFT
    return WarningLevel.NONE


def _read_blocking(day: str) -> _PersistedDay | None:
    p = _path_for(day)
    if not p.exists():
        return None
    with p.open("r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            raw = f.read()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    if not raw.strip():
        raise BudgetCorrupted(f"{p} is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BudgetCorrupted(f"{p} is not valid JSON: {exc}") from exc
    return _PersistedDay.from_dict(parsed)


def _write_blocking(record: _PersistedDay) -> bool:
    """Write today's record under flock. Returns True on success, False on disk-full."""
    _ensure_dir(_state_root())
    p = _path_for(record.day)
    tmp = p.with_suffix(".json.tmp")
    try:
        # Atomic write: open tmp, flock, write, fsync, rename.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = json.dumps(record.to_dict()).encode()
            os.write(fd, data)
            os.fsync(fd)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return True
    except OSError as exc:
        if exc.errno in (28, 122):  # ENOSPC, EDQUOT
            log.warning("Disk full writing budget file %s: %s", p, exc)
            return False
        log.warning("Could not write budget file %s: %s", p, exc)
        return False


class BudgetManager:
    """Two-layer locked accessor for daily spend state."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def read_status(self, day: str | None = None) -> BudgetStatus:
        day = day or _today_str()
        cap = _config.get_budget_daily()
        spent = 0.0
        async with self._lock:
            record = await asyncio.to_thread(_read_blocking, day)
        if record is not None:
            if record.day != day:
                # stale post-midnight — treat today as fresh
                spent = 0.0
            else:
                spent = record.spent_usd
        remaining = max(0.0, cap - spent) if cap > 0 else float("inf")
        return BudgetStatus(
            spent_usd=spent,
            cap_usd=cap,
            remaining_usd=remaining if cap > 0 else 0.0,
            warning_level=_compute_warning_level(spent, cap) if cap > 0 else WarningLevel.NONE,
            day=day,
        )

    async def would_exceed(self, projected_cost: float) -> tuple[bool, BudgetStatus]:
        """Check whether charging ``projected_cost`` would cross the cap.

        If the daily cap is disabled (cap==0), never blocks.
        """
        status = await self.read_status()
        cap = status.cap_usd
        if cap <= 0:
            return False, status
        would_spend = status.spent_usd + max(projected_cost, 0.0)
        return would_spend > cap, status

    async def record_spend(self, amount_usd: float) -> BudgetStatus:
        """Add ``amount_usd`` to today's total. Missing→init, corrupt→fail closed."""
        if amount_usd <= 0:
            return await self.read_status()
        day = _today_str()
        async with self._lock:
            try:
                record = await asyncio.to_thread(_read_blocking, day)
            except BudgetCorrupted:
                raise
            if record is None or record.day != day:
                record = _PersistedDay(day=day, spent_usd=0.0)
            record.spent_usd += amount_usd
            await asyncio.to_thread(_write_blocking, record)
        cap = _config.get_budget_daily()
        remaining = max(0.0, cap - record.spent_usd) if cap > 0 else 0.0
        return BudgetStatus(
            spent_usd=record.spent_usd,
            cap_usd=cap,
            remaining_usd=remaining,
            warning_level=_compute_warning_level(record.spent_usd, cap) if cap > 0 else WarningLevel.NONE,
            day=day,
        )
