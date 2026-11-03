"""C-03/C-06/C-07/C-08: per-analysis worktrees, locks, timeouts, cache upkeep."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from radius_repository.infrastructure import local_git
from radius_repository.infrastructure.local_git import (
    GitTimeoutError,
    GitTimeouts,
    LocalGitRepositoryClient,
)
from radius_repository.infrastructure.repo_lock import (
    RepositoryLockTimeoutError,
    exclusive_lock,
    lock_path_for,
)
from radius_shared.errors import ValidationError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.com")


def _child_env() -> dict[str, str]:
    import radius_repository
    import radius_shared

    paths = [Path(radius_repository.__file__).parents[1], Path(radius_shared.__file__).parents[1]]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([*map(str, paths), env.get("PYTHONPATH", "")])
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *IDENT, *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_cache(root: Path, name: str = "cache") -> tuple[Path, list[str]]:
    """A repository cache with three commits; origin is a valid, never-contacted URL."""

    repo = root / name
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    _git(repo, "remote", "add", "origin", "https://github.com/acme/radius.git")
    shas = []
    for index in range(3):
        (repo / "a.txt").write_text(f"version-{index}", encoding="utf-8")
        (repo / f"only-{index}.txt").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"c{index}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


def test_concurrent_analyses_of_one_repository_each_see_their_own_tree(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    client = LocalGitRepositoryClient()
    roots = tmp_path / "wt"
    barrier = threading.Barrier(3)
    seen: dict[int, tuple[Path, str, bool]] = {}
    errors: list[BaseException] = []

    def analyse(index: int) -> None:
        try:
            with client.analysis_worktree(cache, shas[index], roots, f"analysis-{index}") as tree:
                barrier.wait(timeout=60)  # all three trees exist at the same time
                time.sleep(0.2)  # give a shared-tree implementation time to clobber
                seen[index] = (
                    tree,
                    (tree / "a.txt").read_text(encoding="utf-8"),
                    (tree / f"only-{index}.txt").exists(),
                )
                assert _git(tree, "rev-parse", "HEAD") == shas[index]
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            barrier.abort()

    threads = [threading.Thread(target=analyse, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors, errors
    assert len({tree for tree, _, _ in seen.values()}) == 3
    for index in range(3):
        _tree, content, own_file = seen[index]
        assert content == f"version-{index}"
        assert own_file
    # Removed in the finally block: nothing left, nothing registered.
    assert not any(roots.iterdir())
    assert "worktree " not in "\n".join(
        line for line in _git(cache, "worktree", "list", "--porcelain").splitlines()[2:]
    )


def test_worktree_is_removed_when_the_analysis_fails(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    client = LocalGitRepositoryClient()
    captured: list[Path] = []
    with pytest.raises(RuntimeError), client.analysis_worktree(
        cache, shas[0], tmp_path / "wt", "x"
    ) as tree:
        captured.append(tree)
        assert tree.is_dir()
        raise RuntimeError("analysis blew up")
    assert not captured[0].exists()
    assert not list((cache / ".git" / "worktrees").glob("*"))


def test_the_cache_working_tree_is_never_touched_by_a_worktree(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    client = LocalGitRepositoryClient()
    with client.analysis_worktree(cache, shas[0], tmp_path / "wt", "a") as tree:
        assert (tree / "a.txt").read_text(encoding="utf-8") == "version-0"
        assert (cache / "a.txt").read_text(encoding="utf-8") == "version-2"


def test_worktree_rejects_option_like_and_unknown_refs(tmp_path: Path) -> None:
    cache, _ = _make_cache(tmp_path)
    client = LocalGitRepositoryClient()
    for bad in ("--force", "-b", "a b", "../x"):
        with pytest.raises(ValidationError), client.analysis_worktree(
            cache, bad, tmp_path / "wt", "a"
        ):
            pass
    with pytest.raises(ValidationError), client.analysis_worktree(
        cache, "0" * 40, tmp_path / "wt", "a"
    ):
        pass
    assert not any((tmp_path / "wt").iterdir())


def test_two_processes_serialise_on_the_repository_lock(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    marker = tmp_path / "held"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from radius_repository.infrastructure.repo_lock import exclusive_lock
        with exclusive_lock(Path({str(cache)!r}), 30):
            Path({str(marker)!r}).write_text("1")
            time.sleep(3)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script], env=_child_env())
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        with pytest.raises(RepositoryLockTimeoutError), exclusive_lock(cache, 0.3):
            pass
        started = time.monotonic()
        with exclusive_lock(cache, 30):  # acquired once the child leaves
            waited = time.monotonic() - started
        assert waited < 25
    finally:
        child.wait(timeout=30)


def test_lock_of_a_killed_process_is_recovered(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    marker = tmp_path / "held"
    script = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from radius_repository.infrastructure.repo_lock import exclusive_lock
        with exclusive_lock(Path({str(cache)!r}), 30):
            Path({str(marker)!r}).write_text("1")
            time.sleep(120)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script], env=_child_env())
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert lock_path_for(cache).exists()
        child.kill()  # a crash: the lock file stays, the OS lock does not
        child.wait(timeout=30)
        with exclusive_lock(cache, 10):
            pass
    finally:
        if child.poll() is None:
            child.kill()


def test_in_process_threads_serialise_on_the_lock(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    active = []
    overlap = []

    def work() -> None:
        with exclusive_lock(cache, 30):
            active.append(1)
            if len(active) > 1:
                overlap.append(True)
            time.sleep(0.1)
            active.pop()

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not overlap


# -- C-06 -------------------------------------------------------------------


def test_timeout_bounds_are_clamped() -> None:
    low = GitTimeouts(clone=0, command=-5, lock_wait=0, stale_lock=1)
    assert (low.clone, low.command, low.lock_wait, low.stale_lock) == (5.0, 5.0, 1.0, 30.0)
    high = GitTimeouts(clone=10**9, command=10**9, lock_wait=10**9, stale_lock=10**9)
    assert (high.clone, high.command, high.lock_wait, high.stale_lock) == (
        3600.0,
        1800.0,
        3600.0,
        86400.0,
    )
    default = GitTimeouts()
    assert (default.clone, default.command) == (300.0, 120.0)


def test_run_uses_the_clone_limit_for_clone_and_command_limit_otherwise(
    monkeypatch, tmp_path: Path
) -> None:
    limits = []

    def fake(argv, *, cwd, env, timeout):
        limits.append(timeout)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(local_git, "_exec", fake)
    client = LocalGitRepositoryClient(timeouts=GitTimeouts(clone=111, command=22))
    client._run(("git", "clone", "--", "u", "d"), cwd=None)
    client._run(("git", "fetch"), cwd=None)
    assert limits == [111.0, 22.0]


def test_slow_git_is_killed_with_its_children_and_raises_a_retryable_error(
    monkeypatch, tmp_path: Path
) -> None:
    grandchild_marker = tmp_path / "grandchild-survived"
    fake_git = tmp_path / "fake_git.py"
    fake_git.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            subprocess.Popen([sys.executable, "-c",
                "import time, pathlib; time.sleep(4); "
                "pathlib.Path({str(grandchild_marker)!r}).write_text('x')"])
            time.sleep(120)
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        local_git, "_hardened", lambda command, policy: (sys.executable, str(fake_git))
    )
    timeouts = GitTimeouts()
    object.__setattr__(timeouts, "command", 1.0)  # below the public clamp, test only
    client = LocalGitRepositoryClient(timeouts=timeouts)
    started = time.monotonic()
    with pytest.raises(GitTimeoutError) as excinfo:
        client._run(("git", "fetch"), cwd=tmp_path)
    assert time.monotonic() - started < 30
    assert excinfo.value.retryable is True
    assert "timed out" in str(excinfo.value)
    time.sleep(5)
    assert not grandchild_marker.exists(), "the process group was not killed"


def test_timed_out_clone_leaves_no_half_written_cache(monkeypatch, tmp_path: Path) -> None:
    def fake(argv, *, cwd, env, timeout):
        (tmp_path / "dest").mkdir()
        (tmp_path / "dest" / "partial").write_text("x", encoding="utf-8")
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(local_git, "_exec", fake)
    with pytest.raises(GitTimeoutError):
        LocalGitRepositoryClient().clone_or_fetch(
            "https://github.com/acme/radius.git", tmp_path / "dest"
        )
    assert not (tmp_path / "dest").exists()


def test_lock_wait_timeout_is_a_retryable_error(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    timeouts = GitTimeouts()
    object.__setattr__(timeouts, "lock_wait", 0.2)
    client = LocalGitRepositoryClient(timeouts=timeouts)
    with exclusive_lock(cache, 5):
        holder_done = threading.Event()
        result: list[BaseException] = []

        def contender() -> None:
            try:
                with client.analysis_worktree(cache, shas[0], tmp_path / "wt", "a"):
                    pass
            except BaseException as exc:  # noqa: BLE001
                result.append(exc)
            holder_done.set()

        thread = threading.Thread(target=contender)
        thread.start()
        assert holder_done.wait(30)
        thread.join()
    assert isinstance(result[0], RepositoryLockTimeoutError)
    assert result[0].retryable is True


# -- C-07 -------------------------------------------------------------------


def test_forced_checkout_cannot_be_wedged_by_a_dirty_tree(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    (cache / "a.txt").write_text("local edit", encoding="utf-8")  # would abort a plain checkout
    LocalGitRepositoryClient().checkout(cache, shas[0])
    assert (cache / "a.txt").read_text(encoding="utf-8") == "version-0"
    assert _git(cache, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached


def test_old_index_lock_is_removed_and_a_fresh_one_is_kept(tmp_path: Path) -> None:
    cache, shas = _make_cache(tmp_path)
    client = LocalGitRepositoryClient()
    lock = cache / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    # Fresh: could belong to a live git run by something else -> never removed.
    with pytest.raises(ValidationError):
        client.checkout(cache, shas[0])
    assert lock.exists()
    old = time.time() - client.timeouts.stale_lock - 60
    os.utime(lock, (old, old))
    client.checkout(cache, shas[0])  # recovers
    assert not lock.exists()


def test_maintenance_prunes_idle_caches_but_not_busy_or_in_use_ones(tmp_path: Path) -> None:
    root = tmp_path / "cache-root"
    idle, _ = _make_cache(root / "org1" / "o", "idle-1")
    busy, _ = _make_cache(root / "org1" / "o", "busy-2")
    used, used_shas = _make_cache(root / "org1" / "o", "used-3")
    fresh, _ = _make_cache(root / "org1" / "o", "fresh-4")
    long_ago = time.time() - 40 * 86400
    for repo in (idle, busy, used):
        for path in (repo, repo / ".git" / "FETCH_HEAD"):
            if path.exists():
                os.utime(path, (long_ago, long_ago))
        lock = lock_path_for(repo)
        lock.write_text("old", encoding="utf-8")
        os.utime(lock, (long_ago, long_ago))
    client = LocalGitRepositoryClient()
    wt_root = root / ".worktrees"
    with client.analysis_worktree(used, used_shas[0], wt_root, "live"):
        # the live worktree bumped the lock mtime; age it again to prove the
        # live registration is what protects the cache
        os.utime(lock_path_for(used), (long_ago, long_ago))
        with exclusive_lock(busy, 5):
            report = client.maintain_cache(root, worktrees_root=wt_root, max_idle_days=30)
    assert not idle.exists()
    assert busy.exists(), "a cache whose lock is held must be skipped"
    assert used.exists(), "a cache with a live worktree must be kept"
    assert fresh.exists()
    assert report.repositories_pruned == 1
    assert report.repositories_busy == 1
    # Everything else is untouched when idle pruning is off.
    again = client.maintain_cache(root, worktrees_root=wt_root, max_idle_days=0)
    assert again.repositories_pruned == 0
    assert busy.exists()


def test_maintenance_removes_orphan_worktrees_and_stale_locks(tmp_path: Path) -> None:
    root = tmp_path / "cache-root"
    cache, shas = _make_cache(root / "org" / "o", "r-1")
    client = LocalGitRepositoryClient()
    wt_root = root / ".worktrees"
    # A worker died: worktree directory and registration are left behind.
    dead = client.add_worktree(cache, shas[0], wt_root / "dead")
    old = time.time() - 7 * 3600
    os.utime(dead, (old, old))
    lock = cache / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    ancient = time.time() - 3 * 86400
    os.utime(lock, (ancient, ancient))
    report = client.maintain_cache(root, worktrees_root=wt_root)
    assert report.orphan_worktrees_removed == 1
    assert report.stale_index_locks_removed == 1
    assert not dead.exists()
    assert not list((cache / ".git" / "worktrees").glob("*"))
    assert cache.exists()


def test_maintenance_never_walks_into_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "cache-root"
    cache, shas = _make_cache(root / "org" / "o", "r-1")
    client = LocalGitRepositoryClient()
    wt_root = root / ".worktrees"
    with client.analysis_worktree(cache, shas[0], wt_root, "live") as tree:
        report = client.maintain_cache(root, worktrees_root=wt_root, max_idle_days=1)
        assert tree.exists()
    assert report.repositories_seen == 1


# -- C-08 -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["..", ".", "../x", "a/../../b", ""])
def test_worktree_paths_cannot_leave_their_root(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValidationError):
        local_git._inside(tmp_path / "root", "../escape" if name == "" else name + "/..")
    assert not (tmp_path / "escape").exists()


def test_inside_accepts_a_plain_child(tmp_path: Path) -> None:
    target = local_git._inside(tmp_path / "root", "a-1234")
    assert target.parent == (tmp_path / "root").resolve()
