"""Reference-file loading with path validation.

- repo_root must be canonical absolute, exist, not be '/'
- reference_files must realpath under repo_root
- Per-file cap 1 MiB; total cap 5 MiB across all reference files
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


PER_FILE_MAX_BYTES = 1 * 1024 * 1024
TOTAL_MAX_BYTES = 5 * 1024 * 1024


class PathValidationError(Exception):
    pass


@dataclass
class LoadedReferenceFile:
    relative_path: str
    absolute_path: str
    content: str
    size_bytes: int


@dataclass
class RejectedReferenceFile:
    path: str
    reason: str


def validate_repo_root(raw: str | None) -> str:
    if not raw or not isinstance(raw, str):
        raise PathValidationError("repo_root is required and must be non-empty")
    resolved = os.path.realpath(raw)
    if not resolved or resolved == "/":
        raise PathValidationError(f"repo_root resolves to '{resolved}'")
    if not os.path.isdir(resolved):
        raise PathValidationError(f"repo_root does not exist or is not a directory: {resolved}")
    # Policy: must fall under user's home or under the process CWD.
    home = os.path.realpath(str(Path.home()))
    cwd = os.path.realpath(os.getcwd())
    if not (
        resolved == home
        or resolved.startswith(home + os.sep)
        or resolved == cwd
        or resolved.startswith(cwd + os.sep)
    ):
        raise PathValidationError(
            f"repo_root must be under $HOME or CWD; got {resolved}"
        )
    return resolved


def load_reference_files(
    repo_root: str,
    relative_paths: list[str],
) -> tuple[list[LoadedReferenceFile], list[RejectedReferenceFile]]:
    loaded: list[LoadedReferenceFile] = []
    rejected: list[RejectedReferenceFile] = []
    total = 0
    for raw_path in relative_paths or []:
        if not isinstance(raw_path, str) or not raw_path.strip():
            rejected.append(RejectedReferenceFile(path=str(raw_path), reason="empty_path"))
            continue
        if os.path.isabs(raw_path):
            rejected.append(RejectedReferenceFile(path=raw_path, reason="absolute_path"))
            continue
        joined = os.path.join(repo_root, raw_path)
        resolved = os.path.realpath(joined)
        if not (resolved == repo_root or resolved.startswith(repo_root + os.sep)):
            rejected.append(RejectedReferenceFile(path=raw_path, reason="escapes_repo_root"))
            continue
        if not os.path.isfile(resolved):
            rejected.append(RejectedReferenceFile(path=raw_path, reason="not_a_regular_file"))
            continue
        try:
            size = os.path.getsize(resolved)
        except OSError as exc:
            rejected.append(RejectedReferenceFile(path=raw_path, reason=f"stat_failed:{exc}"))
            continue
        if size > PER_FILE_MAX_BYTES:
            rejected.append(
                RejectedReferenceFile(path=raw_path, reason=f"file_exceeds_{PER_FILE_MAX_BYTES}B")
            )
            continue
        if total + size > TOTAL_MAX_BYTES:
            rejected.append(
                RejectedReferenceFile(path=raw_path, reason="total_size_cap_exceeded")
            )
            continue
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            rejected.append(RejectedReferenceFile(path=raw_path, reason=f"read_failed:{exc}"))
            continue
        total += size
        loaded.append(
            LoadedReferenceFile(
                relative_path=raw_path,
                absolute_path=resolved,
                content=content,
                size_bytes=size,
            )
        )
    return loaded, rejected
