"""The single-container launcher keeps a worker running, within its memory limit, and stops it."""

import json
import subprocess
import sys
import threading
import time

from radius_api.serve_with_worker import (
    KILLED_PREDECESSOR_ENV,
    WorkerSupervisor,
    default_rss_reader,
    lower_priority,
    process_tree_rss_mb,
    worker_max_rss_mb,
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


def test_worker_max_rss_defaults_to_300_and_0_disables() -> None:
    assert worker_max_rss_mb({}) == 300
    assert worker_max_rss_mb({"RADIUS_WORKER_MAX_RSS_MB": "0"}) == 0
    assert worker_max_rss_mb({"RADIUS_WORKER_MAX_RSS_MB": " 256 "}) == 256
    assert worker_max_rss_mb({"RADIUS_WORKER_MAX_RSS_MB": "-5"}) == 0
    assert worker_max_rss_mb({"RADIUS_WORKER_MAX_RSS_MB": "lots"}) == 300


def _write_proc(root, pid: int, ppid: int, rss_kb: int | None, comm: str = "python") -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1 0 -1", encoding="ascii")
    status = "Name:\tx\n" + (f"VmRSS:\t  {rss_kb} kB\n" if rss_kb is not None else "")
    (entry / "status").write_text(status, encoding="ascii")


def test_process_tree_rss_counts_the_worker_and_its_descendants(tmp_path) -> None:
    _write_proc(tmp_path, 10, 1, 1024)  # the worker
    _write_proc(tmp_path, 11, 10, 2048, comm="git (index) x")  # its child, odd comm
    _write_proc(tmp_path, 12, 11, 1024)  # grandchild
    _write_proc(tmp_path, 13, 1, 9999)  # the API, not part of the tree
    _write_proc(tmp_path, 14, 10, None)  # zombie: no VmRSS
    assert process_tree_rss_mb(10, proc_root=str(tmp_path)) == 4.0
    assert process_tree_rss_mb(99, proc_root=str(tmp_path)) is None  # exited


def test_watchdog_is_off_without_a_reader_or_limit() -> None:
    assert not WorkerSupervisor(max_rss_mb=300, rss_reader=None).watchdog_enabled  # Windows
    assert not WorkerSupervisor(max_rss_mb=0, rss_reader=lambda pid: 1.0).watchdog_enabled
    assert WorkerSupervisor(max_rss_mb=300, rss_reader=lambda pid: 1.0).watchdog_enabled
    assert (default_rss_reader() is None) == (not sys.platform.startswith("linux"))


class _FakeProc:
    """A worker that ignores SIGTERM until killed."""

    pid = 4242

    def __init__(self, exits_on_terminate: bool) -> None:
        self.exits_on_terminate = exits_on_terminate
        self.calls: list[str] = []
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.calls.append("terminate")
        if self.exits_on_terminate:
            self.code = -15

    def wait(self, timeout: float | None = None) -> int:
        if self.code is None:
            raise subprocess.TimeoutExpired("worker", timeout or 0)
        return self.code

    def kill(self) -> None:
        self.calls.append("kill")
        self.code = -9


def test_watchdog_terminates_then_kills_a_worker_over_the_limit_and_logs_it() -> None:
    readings = iter([120.0, 280.0, 512.0])
    messages: list[str] = []
    sup = WorkerSupervisor(
        max_rss_mb=300,
        rss_reader=lambda pid: next(readings),
        memory_poll_interval=0.001,
        memory_kill_grace=0.01,
        log=messages.append,
    )
    proc = _FakeProc(exits_on_terminate=False)
    sup._watch_memory(proc)  # returns once the worker is gone
    assert proc.calls == ["terminate", "kill"]
    assert sup.memory_kills == 1
    record = json.loads(messages[0])
    assert record["outcome"] == "worker_memory_exceeded" and record["level"] == "WARNING"
    assert (record["rss_mb"], record["limit_mb"], record["pid"]) == (512, 300, 4242)
    env = sup._child_env()  # the next worker learns which process was killed
    assert env is not None and json.loads(env[KILLED_PREDECESSOR_ENV]) == {
        "pid": 4242,
        "rss_mb": 512,
        "limit_mb": 300,
    }
    assert sup._child_env() is None  # only the next worker


def test_watchdog_leaves_a_worker_under_the_limit_alone() -> None:
    proc = _FakeProc(exits_on_terminate=True)
    calls = {"n": 0}

    def reader(pid: int) -> float | None:
        calls["n"] += 1
        if calls["n"] == 5:
            proc.code = 0  # the worker exits by itself
        return 299.0

    sup = WorkerSupervisor(max_rss_mb=300, rss_reader=reader, memory_poll_interval=0.001)
    sup._watch_memory(proc)
    assert proc.calls == [] and sup.memory_kills == 0 and sup._child_env() is None


def test_supervisor_kills_a_real_worker_over_the_limit_and_restarts_it_with_the_note() -> None:
    spawned: list[dict | None] = []

    def spawn(command, env=None):
        spawned.append(env)
        return subprocess.Popen(command, env=env)

    sup = WorkerSupervisor(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        min_backoff=0.01,
        max_rss_mb=100,
        rss_reader=lambda pid: 400.0 if len(spawned) == 1 else 10.0,
        memory_poll_interval=0.01,
        memory_kill_grace=0.5,
        spawn=spawn,
        log=lambda m: None,
    )
    thread = threading.Thread(target=sup.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while sup.starts < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    sup.stop(grace=5)
    thread.join(timeout=10)
    assert sup.starts == 2 and sup.memory_kills == 1
    assert spawned[0] is None  # the first worker inherits the environment
    assert json.loads(spawned[1][KILLED_PREDECESSOR_ENV])["limit_mb"] == 100
