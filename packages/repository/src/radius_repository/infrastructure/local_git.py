"""Subprocess-backed local Git repository client.

Every value handed to git here may come from a database row or an API caller, so
this module does not trust it: clone URLs are re-validated (https, allow-listed
host, ``owner/repo`` shape), refs are validated, positional arguments follow
``--`` where git supports it, git never goes through a shell, only the ``https``
transport is enabled, and hooks, fsmonitor and credential helpers are switched
off for every invocation.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from radius_shared.errors import RadiusError, ValidationError
from radius_shared.logging import get_logger
from radius_shared.redaction import REDACTED, redact_secrets

from radius_repository.domain.clone_url import GitUrlPolicy, host_of, validate_clone_url
from radius_repository.infrastructure.repo_lock import (
    RepositoryLockTimeoutError,
    exclusive_lock,
    lock_path_for,
)

LOGGER = get_logger(__name__)

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
# A conservative ref/refspec: no leading '-', no whitespace or shell/git magic.
_REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./+:-]{0,254}$")


class GitTimeoutError(RadiusError):
    """A git subprocess exceeded its time limit and was killed; retry the job."""

    code = "GIT_TIMEOUT"
    message = "A git operation timed out."
    retryable = True


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


@dataclass(frozen=True, slots=True)
class GitTimeouts:
    """Time limits (seconds) for git, clamped to sane bounds (C-06/C-07)."""

    clone: float = 300.0
    command: float = 120.0
    lock_wait: float = 300.0
    #: An ``index.lock`` older than this, found while we hold the repository
    #: lock (so no git of ours is using it), is a leftover of a dead process.
    stale_lock: float = 900.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "clone", _clamp(self.clone, 5.0, 3600.0))
        object.__setattr__(self, "command", _clamp(self.command, 5.0, 1800.0))
        object.__setattr__(self, "lock_wait", _clamp(self.lock_wait, 1.0, 3600.0))
        object.__setattr__(self, "stale_lock", _clamp(self.stale_lock, 30.0, 86400.0))


@dataclass(slots=True)
class CacheMaintenanceReport:
    """What one :meth:`LocalGitRepositoryClient.maintain_cache` pass did."""

    repositories_seen: int = 0
    repositories_busy: int = 0
    repositories_pruned: int = 0
    stale_index_locks_removed: int = 0
    orphan_worktrees_removed: int = 0
    errors: int = 0
    pruned: list[str] = field(default_factory=list)


def _safe_ref(value: object, what: str) -> str:
    if (
        not isinstance(value, str)
        or not _REF.match(value)
        or ".." in value
        or value.endswith((".lock", "/"))
    ):
        raise ValidationError(f"Invalid git {what}.")
    return value


class LocalGitRepositoryClient:
    """Clone, fetch, and check out repositories using the Git CLI.

    One directory per repository is the *object cache*: it is cloned and fetched
    under an exclusive lock and its own working tree is never used by analyses.
    Each analysis gets a private ``git worktree`` of the cache (see
    :meth:`analysis_worktree`), so concurrent analyses of different pull
    requests of one repository can never check out over each other (C-03).
    """

    def __init__(
        self,
        policy: GitUrlPolicy | None = None,
        timeouts: GitTimeouts | None = None,
    ) -> None:
        self._policy = policy or GitUrlPolicy()
        self._timeouts = timeouts or GitTimeouts()

    @property
    def policy(self) -> GitUrlPolicy:
        """The clone URL policy this client enforces."""

        return self._policy

    @property
    def timeouts(self) -> GitTimeouts:
        return self._timeouts

    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        """Clone a repository into the cache or fetch updates, under its lock."""

        with self._locked(destination):
            # Checked under the lock: the cache may have been created or pruned
            # while this call waited.
            if destination.exists():
                if not (destination / ".git").exists():
                    msg = f"Destination is not a Git repository: {destination}."
                    raise ValidationError(msg)
                self._clear_stale_locks(destination)
                # The cache was created by an earlier run: do not trust its
                # recorded origin either (it is validated before git talks to it).
                remote = self._validated_origin(destination)
                self._run(
                    ("git", "fetch", "--all", "--prune"),
                    cwd=destination,
                    extra_headers=extra_headers,
                    remote_url=remote,
                )
                return destination

            safe_url = validate_clone_url(clone_url, policy=self._policy)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._run(
                    (
                        "git",
                        "clone",
                        "--no-checkout",
                        "--no-recurse-submodules",
                        "--",
                        safe_url,
                        str(destination),
                    ),
                    cwd=None,
                    extra_headers=extra_headers,
                    remote_url=safe_url,
                )
            except BaseException:
                # A killed or failed clone leaves a half-written directory that
                # would be mistaken for a cache next time.
                _rmtree(destination)
                raise
            return destination

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        """Detach the cache's own working tree at a commit or ref (forced).

        Kept for callers that work on a private clone. Analyses must use
        :meth:`analysis_worktree` instead: this mutates the shared tree.
        """

        self._require_repository(repository_path)
        ref = self._checked_ref(branch_name)
        with self._locked(repository_path):
            self._clear_stale_locks(repository_path)
            self._run(
                ("git", "checkout", "--detach", "--force", ref, "--"),
                cwd=repository_path,
            )

    # -- per-analysis working trees (C-03) ---------------------------------

    def add_worktree(self, repository_path: Path, ref: str, worktree_path: Path) -> Path:
        """Create a detached worktree of ``ref`` at ``worktree_path``."""

        self._require_repository(repository_path)
        checked = self._checked_ref(ref)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(repository_path):
            self._clear_stale_locks(repository_path)
            self._run(("git", "worktree", "prune"), cwd=repository_path)
            self._run(
                (
                    "git",
                    "worktree",
                    "add",
                    "--detach",
                    "--force",
                    "--",
                    str(worktree_path),
                    checked,
                ),
                cwd=repository_path,
            )
        return worktree_path

    def remove_worktree(self, repository_path: Path, worktree_path: Path) -> None:
        """Delete a worktree and its registration. Best effort: never raises."""

        try:
            with self._locked(repository_path):
                if (repository_path / ".git").exists():
                    with contextlib.suppress(Exception):
                        self._run(
                            ("git", "worktree", "remove", "--force", str(worktree_path)),
                            cwd=repository_path,
                        )
                _rmtree(worktree_path)
                if (repository_path / ".git").exists():
                    with contextlib.suppress(Exception):
                        self._run(("git", "worktree", "prune"), cwd=repository_path)
        except Exception as exc:
            _rmtree(worktree_path)
            LOGGER.warning(
                "Could not cleanly remove an analysis worktree",
                extra={"error_type": exc.__class__.__name__},
            )

    @contextlib.contextmanager
    def analysis_worktree(
        self,
        repository_path: Path,
        ref: str,
        worktrees_root: Path,
        name: str,
    ) -> Iterator[Path]:
        """A private checkout of ``ref``, removed when the ``with`` body ends."""

        safe_name = re.sub(r"[^A-Za-z0-9_-]", "-", name)[:64] or "analysis"
        path = _inside(worktrees_root, f"{safe_name}-{uuid.uuid4().hex[:8]}")
        try:
            yield self.add_worktree(repository_path, ref, path)
        finally:
            self.remove_worktree(repository_path, path)

    # -- fetches ------------------------------------------------------------

    def fetch_pull_request(
        self,
        repository_path: Path,
        pr_number: int,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch PR head ref from origin into refs/remotes/origin/pr/<pr_number>."""

        self._require_repository(repository_path)
        if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
            raise ValidationError("Invalid pull request number.")
        with self._locked(repository_path):
            self._clear_stale_locks(repository_path)
            remote = self._validated_origin(repository_path)
            self._run(
                (
                    "git",
                    "fetch",
                    "origin",
                    f"+refs/pull/{pr_number}/head:refs/remotes/origin/pr/{pr_number}",
                ),
                cwd=repository_path,
                extra_headers=extra_headers,
                remote_url=remote,
            )

    def fetch_ref(
        self,
        repository_path: Path,
        remote_ref: str,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch a specific remote ref from origin."""

        self._require_repository(repository_path)
        ref = _safe_ref(remote_ref, "ref")
        with self._locked(repository_path):
            self._clear_stale_locks(repository_path)
            remote = self._validated_origin(repository_path)
            self._run(
                ("git", "fetch", "origin", ref),
                cwd=repository_path,
                extra_headers=extra_headers,
                remote_url=remote,
            )

    # -- maintenance (C-07) ---------------------------------------------------

    def maintain_cache(
        self,
        cache_root: Path,
        *,
        worktrees_root: Path | None = None,
        max_idle_days: int = 0,
        orphan_worktree_seconds: float = 6 * 3600.0,
        now: float | None = None,
    ) -> CacheMaintenanceReport:
        """Housekeeping for every cached repository under ``cache_root``.

        Per repository, only while holding its lock (a busy one is skipped, so a
        cache in use is never touched): drop stale ``index.lock`` files, prune
        dangling worktree registrations, ``git gc --auto``, and, when
        ``max_idle_days`` > 0, delete caches not used for that long and without
        a live worktree. Worktree directories left behind by a dead worker for
        longer than ``orphan_worktree_seconds`` are removed first.
        """

        report = CacheMaintenanceReport()
        current = now if now is not None else time.time()
        worktrees_root = worktrees_root or (cache_root / WORKTREES_DIRNAME)
        if not cache_root.is_dir():
            return report
        report.orphan_worktrees_removed = _remove_orphan_worktrees(
            worktrees_root, current - orphan_worktree_seconds
        )
        for repo in list(_iter_cache_repositories(cache_root, worktrees_root)):
            report.repositories_seen += 1
            # Read before locking: taking the lock stamps the lock file.
            last_used = self._last_used(repo)
            try:
                with exclusive_lock(repo, 0.0):
                    report.stale_index_locks_removed += self._clear_stale_locks(
                        repo, now=current
                    )
                    with contextlib.suppress(Exception):
                        self._run(("git", "worktree", "prune"), cwd=repo)
                    with contextlib.suppress(Exception):
                        self._run(("git", "gc", "--auto", "--quiet"), cwd=repo)
                    if (
                        max_idle_days > 0
                        and last_used < current - max_idle_days * 86400
                        and not any((repo / ".git" / "worktrees").glob("*"))
                    ):
                        _rmtree(repo)
                        report.repositories_pruned += 1
                        report.pruned.append(repo.name)
            except RepositoryLockTimeoutError:
                report.repositories_busy += 1
            except Exception:
                report.errors += 1
        return report

    @staticmethod
    def _last_used(repo: Path) -> float:
        """Newest of the lock-file stamp (every locked operation writes it) and
        the last fetch."""

        stamps = [_mtime(lock_path_for(repo)), _mtime(repo / ".git" / "FETCH_HEAD")]
        return max((s for s in stamps if s is not None), default=_mtime(repo) or 0.0)

    # -- internals ------------------------------------------------------------

    def _locked(self, repository_path: Path):
        return exclusive_lock(repository_path, self._timeouts.lock_wait)

    def _clear_stale_locks(self, repository_path: Path, *, now: float | None = None) -> int:
        """Remove old ``index.lock``-style files. The caller holds the repository
        lock, so no git started by us is using them; the age threshold protects
        git run by something else."""

        cutoff = (now if now is not None else time.time()) - self._timeouts.stale_lock
        git_dir = repository_path / ".git"
        removed = 0
        candidates = [git_dir / "index.lock", git_dir / "shallow.lock"]
        candidates += list((git_dir / "worktrees").glob("*/index.lock"))
        for candidate in candidates:
            stamp = _mtime(candidate)
            if stamp is not None and stamp < cutoff:
                with contextlib.suppress(OSError):
                    candidate.unlink()
                    removed += 1
        return removed

    def _require_repository(self, repository_path: Path) -> None:
        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)

    @staticmethod
    def _checked_ref(branch_name: str) -> str:
        return (
            branch_name
            if isinstance(branch_name, str) and _COMMIT_SHA.match(branch_name)
            else _safe_ref(branch_name, "ref")
        )

    def _validated_origin(self, repository_path: Path) -> str:
        """The checkout's ``origin`` URL, re-validated before git contacts it."""

        recorded = _origin_remote_url(repository_path)
        if recorded is None:
            raise ValidationError("The checkout has no usable 'origin' remote.")
        return validate_clone_url(recorded, policy=self._policy)

    def _run(
        self,
        command: tuple[str, ...],
        cwd: Path | None,
        *,
        extra_headers: tuple[str, ...] = (),
        remote_url: str | None = None,
    ) -> None:
        """Run git, passing credentials only through the child's environment.

        ``extra_headers`` (e.g. ``Authorization: Basic ...``) are handed to git
        as ``GIT_CONFIG_COUNT/KEY_n/VALUE_n`` environment variables, git's
        documented way to set config for one process. Unlike ``-c`` they never
        appear in the command line (``ps``, process listings, crash reports),
        and unlike ``git config`` / a credential URL they are never written to
        ``.git/config``. The header is scoped to the remote's origin, and only
        sent at all when that origin's host is on the allow-list, so it is
        neither replayed to another host after a redirect nor sent to a host a
        stored URL happens to name.

        The child runs in its own process group with a time limit (``clone``
        gets the longer one); on expiry the whole group is killed and a
        retryable :class:`GitTimeoutError` is raised.
        """

        if extra_headers and remote_url is None and cwd is not None:
            remote_url = _origin_remote_url(cwd)
        env = _git_environment(extra_headers, remote_url, self._policy)
        argv = _hardened(command, self._policy)
        operation = command[1] if len(command) > 1 else "git"
        limit = self._timeouts.clone if operation == "clone" else self._timeouts.command
        try:
            result = _exec(argv, cwd=cwd, env=env, timeout=limit)
        except subprocess.TimeoutExpired as exc:
            raise GitTimeoutError(
                f"git {operation} timed out after {limit:g} s and was killed; "
                "the job can be retried."
            ) from exc
        if result.returncode != 0:
            message = (
                (result.stderr or "").strip()
                or (result.stdout or "").strip()
                or f"git exited with status {result.returncode}"
            )
            raise ValidationError(_scrub(message, extra_headers))


WORKTREES_DIRNAME = ".worktrees"


def _exec(
    argv: tuple[str, ...],
    *,
    cwd: Path | None,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` (never a shell) in its own process group with a time limit.

    Raises :class:`subprocess.TimeoutExpired` after killing the whole group.
    """

    kwargs: dict[str, object] = {}
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        shell=False,
        **kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        with contextlib.suppress(Exception):
            process.communicate(timeout=10)
        raise
    except BaseException:
        _kill_process_tree(process)
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Kill the child and everything it spawned (git helpers, ssh, curl)."""

    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        with contextlib.suppress(Exception):
            subprocess.run(  # noqa: S603
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607
                capture_output=True,
                timeout=15,
                check=False,
            )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.kill()


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _rmtree(path: Path) -> None:
    """Remove a tree, clearing read-only bits (git pack files on Windows)."""

    def _make_writable(func, target, _exc):
        with contextlib.suppress(OSError):
            os.chmod(target, stat.S_IWRITE)
            func(target)

    if path.exists():
        shutil.rmtree(path, onexc=_make_writable)


def _inside(root: Path, name: str) -> Path:
    """``root / name`` resolved, refusing anything that escapes ``root`` (C-08)."""

    root.mkdir(parents=True, exist_ok=True)  # resolve() differs before/after on Windows
    base = root.resolve()
    target = (base / name).resolve()
    if target == base or base not in target.parents:
        raise ValidationError("Path escapes the cache directory.")
    return target


def _iter_cache_repositories(cache_root: Path, worktrees_root: Path) -> Iterator[Path]:
    """Directories holding a ``.git`` directory (not worktrees) below the cache root."""

    skip = worktrees_root.resolve()
    for dirpath, dirnames, _files in os.walk(cache_root):
        here = Path(dirpath)
        if here.resolve() == skip:
            dirnames[:] = []
            continue
        if (here / ".git").is_dir():
            dirnames[:] = []
            yield here


def _remove_orphan_worktrees(worktrees_root: Path, cutoff: float) -> int:
    removed = 0
    if not worktrees_root.is_dir():
        return 0
    for child in worktrees_root.iterdir():
        stamp = _mtime(child)
        if stamp is not None and stamp < cutoff:
            _rmtree(child)
            removed += 1
    return removed


def _hardened(command: tuple[str, ...], policy: GitUrlPolicy) -> tuple[str, ...]:
    """Insert per-invocation safety config right after ``git``.

    Only ``https`` (``http`` when the policy allows it, for loopback tests) may
    be used as a transport; ``file``, ``ext``, ``ssh`` and ``git`` are refused.
    Hooks, fsmonitor, credential helpers and submodule recursion are disabled
    because the checked-out content is untrusted.
    """

    config = [
        "protocol.allow=never",
        "protocol.https.allow=always",
        "core.fsmonitor=false",
        f"core.hooksPath={os.devnull}",
        "credential.helper=",
        "submodule.recurse=false",
    ]
    if policy.allow_http:
        config.append("protocol.http.allow=always")
    flags: list[str] = []
    for item in config:
        flags += ["-c", item]
    return (command[0], *flags, *command[1:])


def _origin_remote_url(repository_path: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            _hardened(("git", "config", "--get", "remote.origin.url"), GitUrlPolicy()),
            cwd=repository_path,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() or None


def _header_scope(remote_url: str | None) -> str:
    """Return the git config subsection (``scheme://host[:port]/``) of the remote."""

    if remote_url and host_of(remote_url):
        scheme = remote_url.partition(":")[0].lower()
        if scheme in {"http", "https"}:
            netloc = remote_url.partition("//")[2].partition("/")[0].rpartition("@")[2]
            return f"{scheme}://{netloc}/"
    return ""


def _git_environment(
    extra_headers: tuple[str, ...],
    remote_url: str | None,
    policy: GitUrlPolicy | None = None,
) -> dict[str, str]:
    """Child environment: restricted transports plus the headers as git config."""

    policy = policy or GitUrlPolicy()
    env = dict(os.environ)
    for name in ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF"):
        env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ALLOW_PROTOCOL"] = "http:https" if policy.allow_http else "https"
    if not extra_headers:
        return env
    host = host_of(remote_url)
    if not host or host not in policy.allowed_hosts:
        # Never attach the credential to a host that is not explicitly trusted.
        raise ValidationError("Refusing to send credentials to an untrusted git host.")
    scope = _header_scope(remote_url)
    if not scope:
        raise ValidationError("Refusing to send credentials to an unscoped remote.")
    key = f"http.{scope}.extraHeader"
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        count = 0
    for header in extra_headers:
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = header
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)
    return env


def _scrub(message: str, extra_headers: tuple[str, ...]) -> str:
    """Remove the credential (and its encodings) from git's error output."""

    for header in extra_headers:
        value = header.partition(":")[2].strip()
        for secret in {header, value, value.rpartition(" ")[2]}:
            if len(secret) >= 8:
                message = message.replace(secret, REDACTED)
    return redact_secrets(message.rstrip())
