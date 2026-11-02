"""Ports and adapters that provide repository snapshots (base / head) by path.

The extraction service only needs ``read(path) -> bytes | None``. Adapters:

* :class:`DictSnapshot` - in-memory files (tests, fixtures, API callers)
* :class:`DirectorySnapshot` - a checked-out directory (confined to its root)
* :class:`GitSnapshot` - ``git show <ref>:<path>`` against a local repository
* :class:`DiffReversedSnapshot` - base reconstructed from head + diff when no
  base checkout or ref is available
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Protocol

from radius_analysis.symbol_changes.diff_files import FileDiff
from radius_analysis.symbol_changes.model import FileStatus

GIT_TIMEOUT_SECONDS = 30


class SnapshotReader(Protocol):
    """Read-only view of one repository state."""

    def read(self, path: str) -> bytes | None:
        """Return the file content at ``path`` (repo-relative, ``/``) or ``None``."""


class DictSnapshot:
    def __init__(self, files: Mapping[str, str | bytes]) -> None:
        self._files = {
            k: (v.encode("utf-8") if isinstance(v, str) else bytes(v)) for k, v in files.items()
        }

    def read(self, path: str) -> bytes | None:
        return self._files.get(path)


class DirectorySnapshot:
    """Files below ``root``; paths escaping the root or symlinks yield ``None``."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def read(self, path: str) -> bytes | None:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            return None
        candidate = self._root.joinpath(*pure.parts)
        try:
            if candidate.is_symlink() or not candidate.is_file():
                return None
            candidate.resolve().relative_to(self._root)
            return candidate.read_bytes()
        except (OSError, ValueError):
            return None


class GitSnapshot:
    """``git show ref:path``; local only, never touches the network."""

    def __init__(self, repository_path: Path, ref: str, *, timeout: int = GIT_TIMEOUT_SECONDS):
        if not ref or ref.startswith("-"):
            msg = f"Invalid git ref: {ref!r}"
            raise ValueError(msg)
        self._repo = Path(repository_path)
        self._ref = ref
        self._timeout = timeout
        self._paths: frozenset[str] | None = None
        self._paths_tried = False

    def _tracked_paths(self) -> frozenset[str] | None:
        """Blob paths of ``ref`` from one ``git ls-tree`` (``None`` if it cannot be listed).

        Probing for files that do not exist (manifests, ``__init__.py`` candidates) is
        the common case; answering those from this set avoids one ``git show`` process
        each (about 0.1 s per spawn on Windows, which made tamper analysis time out).
        """

        if not self._paths_tried:
            self._paths_tried = True
            try:
                result = subprocess.run(  # noqa: S603 - fixed argv, ref validated above
                    ["git", "ls-tree", "-r", "-z", "--name-only", self._ref],  # noqa: S607
                    cwd=self._repo,
                    capture_output=True,
                    check=False,
                    timeout=self._timeout,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if result.returncode == 0:
                names = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
                self._paths = frozenset(n for n in names if n)
        return self._paths

    def read(self, path: str) -> bytes | None:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            return None
        tracked = self._tracked_paths()
        if tracked is not None and path not in tracked:
            return None
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, ref validated above
                ["git", "show", f"{self._ref}:{path}"],  # noqa: S607
                cwd=self._repo,
                capture_output=True,
                check=False,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None


class DiffReversedSnapshot:
    """Base snapshot rebuilt by reverse-applying ``diffs`` onto the head snapshot.

    Returns ``None`` when a hunk's head-side lines do not match (the diff does
    not belong to that head), so callers degrade to file-level instead of
    reporting nonsense.
    """

    def __init__(self, head: SnapshotReader, diffs: list[FileDiff]) -> None:
        self._head = head
        self._by_old = {d.old_path: d for d in diffs if d.old_path is not None}
        self._absent = {
            d.new_path
            for d in diffs
            if d.new_path is not None and d.status in {FileStatus.ADDED, FileStatus.COPIED}
        }

    def read(self, path: str) -> bytes | None:
        diff = self._by_old.get(path)
        if diff is None:
            return None if path in self._absent else self._head.read(path)
        if diff.binary or diff.status is FileStatus.ADDED:
            return None
        if diff.status is FileStatus.DELETED:
            head_lines: list[str] = [""]
        else:
            data = self._head.read(diff.new_path or path)
            if data is None:
                return None
            head_lines = data.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n")
        for hunk in sorted(diff.hunks, key=lambda h: h.new_start, reverse=True):
            new_side = [ln.text.rstrip("\r") for ln in hunk.lines if ln.tag in " +"]
            old_side = [ln.text.rstrip("\r") for ln in hunk.lines if ln.tag in " -"]
            start = hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
            if diff.status is FileStatus.DELETED:
                start = 0
                new_side = []
            if head_lines[start : start + len(new_side)] != new_side:
                return None
            head_lines[start : start + len(new_side)] = old_side
        return "\n".join(head_lines).encode("utf-8")
