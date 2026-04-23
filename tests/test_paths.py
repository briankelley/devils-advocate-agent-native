import os
from pathlib import Path

import pytest

from dvad_agent import paths as _paths


def test_validate_rejects_empty():
    with pytest.raises(_paths.PathValidationError):
        _paths.validate_repo_root("")


def test_validate_rejects_root():
    with pytest.raises(_paths.PathValidationError):
        _paths.validate_repo_root("/")


def test_validate_rejects_nonexistent(tmp_path):
    with pytest.raises(_paths.PathValidationError):
        _paths.validate_repo_root(str(tmp_path / "does_not_exist"))


def test_validate_accepts_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    resolved = _paths.validate_repo_root(str(repo))
    assert resolved == str(repo.resolve())


def test_load_reference_files_rejects_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.txt").write_text("ok")
    resolved = _paths.validate_repo_root(str(repo))
    loaded, rejected = _paths.load_reference_files(resolved, ["/etc/passwd"])
    assert loaded == []
    assert rejected and rejected[0].reason == "absolute_path"


def test_load_reference_files_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "secrets.txt").write_text("shh")
    resolved = _paths.validate_repo_root(str(repo))
    loaded, rejected = _paths.load_reference_files(resolved, ["../secrets.txt"])
    assert loaded == []
    assert rejected and rejected[0].reason == "escapes_repo_root"


def test_load_reference_files_size_cap_per_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    big = repo / "big.bin"
    big.write_bytes(b"x" * (2 * 1024 * 1024))
    resolved = _paths.validate_repo_root(str(repo))
    loaded, rejected = _paths.load_reference_files(resolved, ["big.bin"])
    assert loaded == []
    assert rejected and "exceeds" in rejected[0].reason


def test_load_reference_files_happy_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "sub" / "a.py").write_text("print('a')")
    resolved = _paths.validate_repo_root(str(repo))
    loaded, rejected = _paths.load_reference_files(resolved, ["sub/a.py"])
    assert rejected == []
    assert len(loaded) == 1
    assert loaded[0].content == "print('a')"
