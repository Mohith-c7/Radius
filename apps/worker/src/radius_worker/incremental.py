"""Git facts for incremental graph builds: the nearest analysed ancestor and the diff.

An incremental build patches the stored graph of an ancestor of the head commit
(usually the previous push to the same pull request, or a merged pull request head on
the target branch). Everything here is read-only git plumbing on the analysis worktree;
any git problem returns ``None`` and the caller builds the full graph.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from radius_shared.logging import get_logger

LOGGER = get_logger(__name__)

#: How many commits back from the head the search for a stored snapshot goes.
MAX_ANCESTOR_COMMITS = 200
_GIT_TIMEOUT_SECONDS = 60.0


def _git(repository_path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=repository_path,
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="surrogateescape")


def nearest_snapshot_ancestor(
    repository_path: Path,
    head_ref: str,
    candidates: Mapping[str, UUID],
    *,
    max_commits: int = MAX_ANCESTOR_COMMITS,
) -> tuple[str, UUID] | None:
    """The newest ancestor of ``head_ref`` (itself included) with a stored snapshot."""

    if not candidates:
        return None
    output = _git(
        repository_path, "rev-list", f"--max-count={max_commits}", f"{head_ref}^{{commit}}", "--"
    )
    if output is None:
        return None
    for line in output.splitlines():
        sha = line.strip().lower()
        if sha in candidates:
            return sha, candidates[sha]
    return None


def changed_paths_between(
    repository_path: Path, base_sha: str, head_ref: str
) -> tuple[str, ...] | None:
    """Every path whose content differs between the two trees (renames as delete + add)."""

    output = _git(
        repository_path,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        f"{base_sha}^{{commit}}",
        f"{head_ref}^{{commit}}",
        "--",
    )
    if output is None:
        return None
    return tuple(sorted({path for path in output.split("\0") if path}))
