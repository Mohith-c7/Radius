"""The per-repository object cache is reused across jobs (``sync_cache``).

Network git (clone/fetch) is intercepted and recorded; every other git command runs
for real against a local repository whose origin is a valid, never-contacted URL.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from radius_repository.infrastructure import local_git
from radius_repository.infrastructure.local_git import LocalGitRepositoryClient

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

URL = "https://github.com/acme/radius.git"
HEADER = "Authorization: Basic c2VjcmV0"
IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.com")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *IDENT, *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_repo(path: Path) -> str:
    subprocess.run(("git", "init", "-q", str(path)), check=True)
    _git(path, "remote", "add", "origin", URL)
    (path / "a.txt").write_text("a", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c")
    return _git(path, "rev-parse", "HEAD")


@pytest.fixture
def network(monkeypatch):
    """Record clone/fetch argv (and the credential env); a clone creates a local repo."""

    calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
    real = local_git._exec

    def fake(argv, *, cwd, env, timeout):
        op = next((a for a in ("clone", "fetch") if a in argv), None)
        if op is None:
            return real(argv, cwd=cwd, env=env, timeout=timeout)
        calls.append((op, tuple(argv[argv.index(op) + 1 :]), env))
        if op == "clone":
            _make_repo(Path(argv[-1]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(local_git, "_exec", fake)
    return calls


def _sync(dest: Path, **kw) -> Path:
    return LocalGitRepositoryClient().sync_cache(
        URL, dest, branches=("develop",), pull_request=7, extra_headers=(HEADER,), **kw
    )


def test_cache_miss_clones_once_then_fetches_the_pr_ref(network, tmp_path: Path) -> None:
    dest = tmp_path / "cache" / "radius"
    assert _sync(dest) == dest
    assert [op for op, _, _ in network] == ["clone", "fetch"]
    assert network[1][1] == ("origin", "+refs/pull/7/head:refs/remotes/origin/pr/7")


def test_cache_hit_fetches_only_the_base_branch_and_pr_head(network, tmp_path: Path) -> None:
    dest = tmp_path / "radius"
    sha = _make_repo(dest)
    _sync(dest, commit=sha)
    ((op, args, env),) = network
    assert op == "fetch"
    assert args == (
        "origin",
        "+refs/heads/develop:refs/remotes/origin/develop",
        "+refs/pull/7/head:refs/remotes/origin/pr/7",
    )
    # credentials only through the child's environment, never in .git/config or argv
    assert HEADER in env.values()
    assert "Basic" not in (dest / ".git" / "config").read_text(encoding="utf-8")
    assert not any("Basic" in a for a in args)


def test_missing_commit_after_a_targeted_fetch_fetches_every_ref(network, tmp_path: Path) -> None:
    dest = tmp_path / "radius"
    _make_repo(dest)
    _sync(dest, commit="f" * 40)
    assert [args for _, args, _ in network][1] == ("--all", "--prune")


@pytest.mark.parametrize("damage", ["not_a_repo", "broken_git_dir", "bad_origin"])
def test_unusable_cache_is_cloned_again(network, tmp_path: Path, damage: str) -> None:
    dest = tmp_path / "radius"
    if damage == "not_a_repo":
        dest.mkdir()
        (dest / "junk.txt").write_text("x", encoding="utf-8")
    elif damage == "broken_git_dir":
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "HEAD").write_text("garbage", encoding="utf-8")
    else:
        _make_repo(dest)
        _git(dest, "remote", "set-url", "origin", "file:///etc")
    _sync(dest)
    assert network[0][0] == "clone"
    assert not (dest / "junk.txt").exists()
    assert _git(dest, "config", "--get", "remote.origin.url") == URL


def test_failed_targeted_fetch_falls_back_to_fetching_every_ref(monkeypatch, tmp_path) -> None:
    dest = tmp_path / "radius"
    _make_repo(dest)
    seen: list[tuple[str, ...]] = []
    real = local_git._exec

    def fake(argv, *, cwd, env, timeout):
        if "fetch" not in argv:
            return real(argv, cwd=cwd, env=env, timeout=timeout)
        args = tuple(argv[argv.index("fetch") + 1 :])
        seen.append(args)
        failed = args[0] == "origin"  # the targeted fetch (e.g. the PR ref is gone)
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "", "missing ref" if failed else "")

    monkeypatch.setattr(local_git, "_exec", fake)
    _sync(dest)
    assert seen[-1] == ("--all", "--prune")


def test_worktrees_of_a_cached_repository_are_private(network, tmp_path: Path) -> None:
    dest = tmp_path / "radius"
    sha = _make_repo(dest)
    client = LocalGitRepositoryClient()
    client.sync_cache(URL, dest, commit=sha)
    with client.analysis_worktree(dest, sha, tmp_path / "wt", "a") as one, client.analysis_worktree(
        dest, sha, tmp_path / "wt", "b"
    ) as two:
        assert one != two and (one / "a.txt").exists() and (two / "a.txt").exists()
    assert not one.exists() and not two.exists()
