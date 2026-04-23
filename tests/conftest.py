"""Test config — clear env and point budget storage at a tempdir for each test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    # Strip any real API keys so tests don't accidentally fire real calls.
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_BASE_URL",
        "DVAD_BUDGET_PER_REVIEW",
        "DVAD_BUDGET_DAILY",
        "DVAD_SECRETS_MODE",
        "DVAD_PERSIST_REVIEWS",
        "DVAD_LOG_LEVEL",
        "DVAD_HOME",
    ):
        monkeypatch.delenv(var, raising=False)
    # Isolate budget / XDG state per test
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    # Point HOME into tmp to prevent install command etc. from finding real config
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    yield
