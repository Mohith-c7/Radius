"""Run the API and the worker in one container (single-instance hosting).

For hosts that give you one process slot only (for example a free Render web service,
which has no background workers):

    python -m radius_api.serve_with_worker

1. ``alembic upgrade head`` (same as the image's default command; exits on failure).
2. The worker (``python -m radius_worker``) in a child process, restarted with a capped
   backoff whenever it exits, so a crash never leaves the queue unattended.
3. uvicorn in the foreground on ``$PORT`` (default 8000). When it stops (SIGTERM on
   redeploy), the worker is asked to stop and given time to finish its job, then killed.

The normal deployment (separate api and worker services, docker compose) does not use this.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence

WORKER_COMMAND: tuple[str, ...] = (sys.executable, "-m", "radius_worker")
MIGRATE_COMMAND: tuple[str, ...] = (sys.executable, "-m", "alembic", "upgrade", "head")


class WorkerSupervisor:
    """Keep one worker process running until :meth:`stop`; restart it with backoff."""

    def __init__(
        self,
        command: Sequence[str] = WORKER_COMMAND,
        *,
        min_backoff: float = 2.0,
        max_backoff: float = 60.0,
        healthy_after: float = 60.0,
        spawn: Callable[[Sequence[str]], subprocess.Popen] = subprocess.Popen,
        log: Callable[[str], None] = lambda m: print(m, flush=True),
    ) -> None:
        self._command = tuple(command)
        self._min, self._max, self._healthy = min_backoff, max_backoff, healthy_after
        self._spawn, self._log = spawn, log
        self._stopping = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.starts = 0

    def run(self) -> None:
        backoff = self._min
        while not self._stopping.is_set():
            with self._lock:
                if self._stopping.is_set():
                    return
                self._proc = self._spawn(self._command)
                self.starts += 1
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
    supervisor = WorkerSupervisor()
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
