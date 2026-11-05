"""Cross-process, cross-thread exclusive lock for one repository cache (C-03).

The lock is an OS advisory lock (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
Windows) on a sibling ``<cache>.lock`` file, plus an in-process mutex so threads
queue in order. Because the kernel drops the lock when its holder exits, a
crashed worker can never leave a *stale* lock behind: the next acquirer simply
gets it. Acquisition polls with a timeout and raises a retryable error instead
of waiting forever.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from radius_shared.errors import RadiusError

try:  # pragma: no cover - platform specific import
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

_POLL_SECONDS = 0.05
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class RepositoryLockTimeoutError(RadiusError):
    """The repository cache stayed locked past the wait limit; retry the job."""

    code = "GIT_LOCK_TIMEOUT"
    message = "Timed out waiting for the repository cache lock."
    retryable = True


def lock_path_for(repository_path: Path) -> Path:
    """The lock file that guards ``repository_path`` (a sibling, so it exists
    before the cache does and survives the cache being deleted)."""

    return repository_path.with_name(repository_path.name + ".lock")


def _thread_lock(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _try_flock(handle: int) -> bool:
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - Windows
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _release_flock(handle: int) -> None:
    with contextlib.suppress(OSError):
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_UN)
        else:  # pragma: no cover - Windows
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def exclusive_lock(repository_path: Path, timeout: float) -> Iterator[Path]:
    """Hold the exclusive lock of ``repository_path`` for the ``with`` body."""

    lock_file = lock_path_for(repository_path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout, 0.0)
    mutex = _thread_lock(str(lock_file.resolve()))
    if not mutex.acquire(timeout=max(timeout, 0.0)):
        raise RepositoryLockTimeoutError
    handle = -1
    try:
        handle = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        while not _try_flock(handle):
            if time.monotonic() >= deadline:
                raise RepositoryLockTimeoutError
            time.sleep(_POLL_SECONDS)
        # Diagnostic only; the OS lock is the source of truth. Also bumps the
        # mtime, which the cache pruner reads as "last used".
        with contextlib.suppress(OSError):
            os.ftruncate(handle, 0)
            os.lseek(handle, 0, os.SEEK_SET)
            os.write(handle, f"{os.getpid()} {int(time.time())}\n".encode())
            os.lseek(handle, 0, os.SEEK_SET)
        try:
            yield lock_file
        finally:
            _release_flock(handle)
    finally:
        if handle >= 0:
            with contextlib.suppress(OSError):
                os.close(handle)
        mutex.release()


def try_exclusive_lock(repository_path: Path):
    """Like :func:`exclusive_lock` with no waiting; use as ``with`` and catch
    :class:`RepositoryLockTimeoutError` to skip a busy repository."""

    return exclusive_lock(repository_path, 0.0)
