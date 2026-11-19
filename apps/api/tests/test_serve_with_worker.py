"""The single-container launcher keeps a worker running and stops it cleanly."""

import sys
import threading
import time

from radius_api.serve_with_worker import WorkerSupervisor


def test_worker_is_restarted_after_it_exits_and_stop_ends_the_loop() -> None:
    messages: list[str] = []
    sup = WorkerSupervisor(
        (sys.executable, "-c", "pass"),  # exits immediately, like a crash
        min_backoff=0.01, max_backoff=0.02, log=messages.append,
    )
    thread = threading.Thread(target=sup.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while sup.starts < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    sup.stop(grace=5)
    thread.join(timeout=5)
    assert sup.starts >= 3
    assert not thread.is_alive()
    assert all("restarting" in m for m in messages)


def test_stop_terminates_a_running_worker() -> None:
    sup = WorkerSupervisor((sys.executable, "-c", "import time; time.sleep(60)"), log=lambda m: None)
    thread = threading.Thread(target=sup.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while sup.starts < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    sup.stop(grace=5)
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert sup.starts == 1  # not restarted after a deliberate stop
    assert time.monotonic() - started < 10
