"""The single-container launcher keeps a worker running and stops it cleanly."""

import sys
import threading
import time

from radius_api.serve_with_worker import (
    WorkerSupervisor,
    lower_priority,
    worker_niceness,
)


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


def test_worker_niceness_defaults_to_10_and_0_disables() -> None:
    assert worker_niceness({}) == 10
    assert worker_niceness({"RADIUS_WORKER_NICE": "0"}) == 0
    assert worker_niceness({"RADIUS_WORKER_NICE": " 5 "}) == 5
    assert worker_niceness({"RADIUS_WORKER_NICE": "99"}) == 19
    assert worker_niceness({"RADIUS_WORKER_NICE": "-3"}) == 0
    assert worker_niceness({"RADIUS_WORKER_NICE": "high"}) == 10


def test_lower_priority_sets_the_child_nice_value_or_is_a_no_op() -> None:
    calls: list[tuple[int, int, int]] = []
    assert lower_priority(42, 10, setpriority=lambda *a: calls.append(a)) is True
    assert calls[0][1:] == (42, 10)
    assert lower_priority(42, 0, setpriority=lambda *a: calls.append(a)) is False
    assert lower_priority(42, 10, setpriority=None) is False  # Windows: no os.setpriority
    assert len(calls) == 1

    def denied(*_a: int) -> None:
        raise PermissionError("not permitted")

    messages: list[str] = []
    assert lower_priority(42, 10, setpriority=denied, log=messages.append) is False
    assert "could not lower worker priority" in messages[0]


def test_supervisor_lowers_the_priority_of_each_spawned_worker() -> None:
    reniced: list[tuple[int, int]] = []
    sup = WorkerSupervisor(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        niceness=7,
        renice=lambda pid, nice, log: reniced.append((pid, nice)) or True,
        log=lambda m: None,
    )
    thread = threading.Thread(target=sup.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not reniced and time.monotonic() < deadline:
        time.sleep(0.01)
    sup.stop(grace=5)
    thread.join(timeout=10)
    assert len(reniced) == 1 and reniced[0][1] == 7 and reniced[0][0] > 0
