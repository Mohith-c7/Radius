"""Reproducibility metadata that needs I/O: git state and file hashes."""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def git_state(cwd: Path | None = None) -> dict[str, Any]:
    """Current commit sha and whether the working tree has changes."""
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    sha = run("rev-parse", "HEAD")
    if not sha:
        return {"sha": "unknown", "dirty": None}
    status = run("status", "--porcelain")
    return {"sha": sha, "dirty": bool(status) if status is not None else None}


def hash_path(path: Path) -> str:
    """SHA-256 over a file, or over a directory's files (sorted relative paths)."""
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def environment() -> dict[str, str]:
    return {"python": sys.version.split()[0], "platform": platform.platform()}
