"""Git diff collection for open and already-merged pull request heads."""

import shutil
import subprocess
from pathlib import Path

import pytest
from radius_analysis.infrastructure.git_diff_provider import SubprocessGitDiffProvider

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "core.py", "def f():\n    return 1\n", "base")
    return tmp_path


def test_open_pull_request_diff(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _commit(repo, "core.py", "def f():\n    return 2\n", "change")

    diff = SubprocessGitDiffProvider().get_diff(repo, "main", head)

    assert "+    return 2" in diff


def test_merged_pull_request_diff_uses_base_before_merge(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _commit(repo, "core.py", "def f():\n    return 2\n", "change")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "other.py", "x = 1\n", "unrelated work on main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature")
    _commit(repo, "later.py", "y = 1\n", "work after the merge")

    diff = SubprocessGitDiffProvider().get_diff(repo, "main", head)

    assert "+    return 2" in diff
    assert "other.py" not in diff
    assert "later.py" not in diff
