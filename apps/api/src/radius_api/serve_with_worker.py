"""Run the API and the worker in one container (single-instance hosting).

For hosts that give you one process slot only (for example a free Render web service,
which has no background workers):

    python -m radius_api.serve_with_worker

1. ``alembic upgrade head`` (same as the image's default command; exits on failure).
2. The worker (``python -m radius_worker``) in a child process, restarted with a capped
   backoff whenever it exits, so a crash never leaves the queue unattended.
   On POSIX the worker runs at a lower CPU priority (``RADIUS_WORKER_NICE``, default 10,
   0 disables) so a running analysis does not starve API requests on a small container.
   On Linux a memory watchdog polls the worker's resident memory (its process tree,
   ``/proc/<pid>/status`` VmRSS) every second and kills it when it exceeds
   ``RADIUS_WORKER_MAX_RSS_MB`` (default 300, 0 disables), so one large analysis cannot take
   the whole container (and the API) past the host's memory limit. The next worker is told
   which process was killed and releases its job: it is retried up to
   ``WORKER_JOB_MAX_ATTEMPTS`` and then failed with "Analysis exceeded the memory budget".
3. uvicorn in the foreground on ``$PORT`` (default 8000). When it stops (SIGTERM on
   redeploy), the worker is asked to stop and given time to finish its job, then killed.

The normal deployment (separate api and worker services, docker compose) does not use this.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence

WORKER_COMMAND: tuple[str, ...] = (sys.executable, "-m", "radius_worker")
MIGRATE_COMMAND: tuple[str, ...] = (sys.executable, "-m", "alembic", "upgrade", "head")
DEFAULT_WORKER_NICE = 10
DEFAULT_WORKER_MAX_RSS_MB = 300
#: Read by the next worker to release the killed worker's job. Same value as
#: ``radius_worker.runner.KILLED_PREDECESSOR_ENV`` (the API does not import the worker).
KILLED_PREDECESSOR_ENV = "RADIUS_WORKER_KILLED_PREDECESSOR"


def worker_niceness(env: Mapping[str, str] = os.environ) -> int:
    """``RADIUS_WORKER_NICE`` clamped to 0..19; default 10, 0 disables, invalid -> default."""

    raw = env.get("RADIUS_WORKER_NICE", "").strip()
    if not raw:
        return DEFAULT_WORKER_NICE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WORKER_NICE
    return max(0, min(value, 19))


def worker_max_rss_mb(env: Mapping[str, str] = os.environ) -> int:
    """``RADIUS_WORKER_MAX_RSS_MB``; default 300, 0 or negative disables, invalid -> default."""

    raw = env.get("RADIUS_WORKER_MAX_RSS_MB", "").strip()
    if not raw:
        return DEFAULT_WORKER_MAX_RSS_MB
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_WORKER_MAX_RSS_MB


def _status_rss_kb(proc_root: str, pid: int) -> int:
    try:
        with open(f"{proc_root}/{pid}/status", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0  # exited, or a zombie / kernel thread without VmRSS


def _parent_of(proc_root: str, pid: str) -> int | None:
    try:
        with open(f"{proc_root}/{pid}/stat", encoding="ascii", errors="replace") as fh:
            stat = fh.read()
        # "pid (comm) state ppid ...": comm may contain spaces and parentheses.
        return int(stat[stat.rindex(")") + 2 :].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def process_tree_rss_mb(pid: int, proc_root: str = "/proc") -> float | None:
    """Resident memory (MB) of ``pid`` plus all its descendants; ``None`` once it is gone.

    Linux only (reads ``/proc``). Descendants count because the worker runs ``git`` and,
    with the sandbox on, test processes.
    """

    if not os.path.exists(f"{proc_root}/{pid}"):
        return None
    children: dict[int, list[int]] = {}
    try:
        entries = [entry for entry in os.listdir(proc_root) if entry.isdigit()]
    except OSError:
        entries = []
    for entry in entries:
        parent = _parent_of(proc_root, entry)
        if parent is not None:
            children.setdefault(parent, []).append(int(entry))
    total_kb, stack, seen = 0, [pid], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        total_kb += _status_rss_kb(proc_root, current)
        stack.extend(children.get(current, ()))
    return total_kb / 1024


def default_rss_reader() -> Callable[[int], float | None] | None:
    """The ``/proc`` reader on Linux; ``None`` elsewhere, which turns the watchdog off."""

    return process_tree_rss_mb if sys.platform.startswith("linux") else None


def lower_priority(
    pid: int,
    niceness: int,
    *,
    setpriority: Callable[[int, int, int], None] | None = getattr(os, "setpriority", None),
    log: Callable[[str], None] = lambda m: print(m, flush=True),
) -> bool:
    """Set the child's nice value (POSIX). A no-op on Windows or when ``niceness`` is 0."""

    if niceness <= 0 or setpriority is None:
        return False
    try:
        setpriority(getattr(os, "PRIO_PROCESS", 0), pid, niceness)
    except OSError as exc:
        log(f"serve_with_worker: could not lower worker priority: {exc}")
        return False
    return True


class WorkerSupervisor:
    """Keep one worker process running until :meth:`stop`; restart it with backoff.

    With ``max_rss_mb`` > 0 and an ``rss_reader`` (Linux), a watchdog thread kills a worker
    whose resident memory exceeds the limit; the next worker gets
    :data:`KILLED_PREDECESSOR_ENV` so it can release the killed worker's job at once.
    """

    def __init__(
        self,
        command: Sequence[str] = WORKER_COMMAND,
        *,
        min_backoff: float = 2.0,
        max_backoff: float = 60.0,
        healthy_after: float = 60.0,
        niceness: int = 0,
        max_rss_mb: int = 0,
        rss_reader: Callable[[int], float | None] | None = None,
        memory_poll_interval: float = 1.0,
        memory_kill_grace: float = 3.0,
        spawn: Callable[..., subprocess.Popen] = subprocess.Popen,
        renice: Callable[..., bool] = lower_priority,
        log: Callable[[str], None] = lambda m: print(m, flush=True),
    ) -> None:
        self._command = tuple(command)
        self._min, self._max, self._healthy = min_backoff, max_backoff, healthy_after
        self._spawn, self._log = spawn, log
        self._niceness, self._renice = niceness, renice
        self._max_rss_mb, self._rss_reader = max_rss_mb, rss_reader
        self._poll, self._kill_grace = memory_poll_interval, memory_kill_grace
        self._stopping = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        #: Set when the watchdog killed the current worker; handed to the next one.
        self._killed: dict[str, int] | None = None
        self.starts = 0
        self.memory_kills = 0

    @property
    def watchdog_enabled(self) -> bool:
        return self._max_rss_mb > 0 and self._rss_reader is not None

    def run(self) -> None:
        backoff = self._min
        while not self._stopping.is_set():
            with self._lock:
                if self._stopping.is_set():
                    return
                env = self._child_env()
                if env is None:
                    self._proc = self._spawn(self._command)
                else:
                    self._proc = self._spawn(self._command, env=env)
                self.starts += 1
            if self._niceness > 0:
                self._renice(self._proc.pid, self._niceness, log=self._log)
            if self.watchdog_enabled:
                threading.Thread(
                    target=self._watch_memory,
                    args=(self._proc,),
                    name="worker-memory-watchdog",
                    daemon=True,
                ).start()
            started = time.monotonic()
            code = self._proc.wait()
            if self._stopping.is_set():
                return
            # A worker that ran for a while before exiting starts the backoff over.
            backoff = self._min if time.monotonic() - started >= self._healthy else backoff
            self._log(f"serve_with_worker: worker exited with {code}; restarting in {backoff:.0f}s")
            if self._stopping.wait(backoff):
                return
            backoff = min(backoff * 2, self._max)

    def _child_env(self) -> dict[str, str] | None:
        """Environment for the next worker: ``None`` (inherit) unless one was killed."""

        if self._killed is None:
            return None
        env = dict(os.environ)
        env[KILLED_PREDECESSOR_ENV] = json.dumps(self._killed)
        self._killed = None
        return env

    def _watch_memory(self, proc: subprocess.Popen) -> None:
        """Poll the worker's RSS; terminate, then kill, it once it exceeds the limit."""

        reader = self._rss_reader
        if reader is None:
            return
        while proc.poll() is None and not self._stopping.wait(self._poll):
            rss = reader(proc.pid)
            if rss is None or rss <= self._max_rss_mb:
                continue
            if proc.poll() is not None or self._stopping.is_set():
                return
            self._killed = {"pid": proc.pid, "rss_mb": round(rss), "limit_mb": self._max_rss_mb}
            self.memory_kills += 1
            self._log(
                json.dumps(
                    {
                        "level": "WARNING",
                        "message": "worker exceeded RADIUS_WORKER_MAX_RSS_MB; killing it",
                        "logger": "radius_api.serve_with_worker",
                        "outcome": "worker_memory_exceeded",
                        "pid": proc.pid,
                        "rss_mb": round(rss),
                        "limit_mb": self._max_rss_mb,
                    }
                )
            )
            # The worker would finish its job on SIGTERM: allow only a short grace.
            proc.terminate()
            try:
                proc.wait(timeout=self._kill_grace)
            except subprocess.TimeoutExpired:
                proc.kill()
            return

    def stop(self, grace: float = 30.0) -> None:
        self._stopping.set()
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()  # the worker finishes its current job on SIGTERM
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    if subprocess.call(MIGRATE_COMMAND) != 0:
        print("serve_with_worker: migrations failed; not starting", file=sys.stderr, flush=True)
        return 1
    max_rss_mb = worker_max_rss_mb()
    supervisor = WorkerSupervisor(
        niceness=worker_niceness(),
        max_rss_mb=max_rss_mb,
        rss_reader=default_rss_reader(),
    )
    if supervisor.watchdog_enabled:
        print(f"serve_with_worker: worker memory limit {max_rss_mb} MB", flush=True)
    thread = threading.Thread(target=supervisor.run, name="worker-supervisor", daemon=True)
    thread.start()
    try:
        import uvicorn

        uvicorn.run("radius_api.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    finally:
        supervisor.stop(grace=float(os.environ.get("RADIUS_EMBEDDED_WORKER_GRACE_SECONDS", "30")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
