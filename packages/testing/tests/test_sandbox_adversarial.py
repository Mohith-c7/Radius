"""Adversarial proof that the container sandbox contains hostile test code.

Every payload below runs ONLY inside the sandbox container, which is started
with hard limits (``--network none``, ``--read-only``, ``--cap-drop ALL``,
``--pids-limit``, ``--memory``, ``--cpus``, ulimits, a wall-clock timeout and a
tmpfs size cap). Payloads are written into a throw-away repository snapshot and
are never imported or executed in the test process or on the host.

Select / require them in CI with the ``sandbox_adversarial`` marker::

    RADIUS_REQUIRE_SANDBOX_TESTS=true pytest -m sandbox_adversarial

They skip (with a reason) when docker or the image is unavailable, unless
``RADIUS_REQUIRE_SANDBOX_TESTS=true``, in which case a missing runtime is an
error so a silent skip cannot hide an isolation regression.

Each test asserts the runner CLASSIFIED the outcome (``ERROR``/timeout/killed,
never ``PASSED`` for a resource attack) or that the payload itself observed the
denial (``DENIED`` markers) and no ``BREACH`` marker was printed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from uuid import uuid4

import pytest
from radius_testing.domain import TestCase as RadiusTestCase
from radius_testing.domain import TestFramework as RadiusTestFramework
from radius_testing.domain import TestName as RadiusTestName
from radius_testing.domain import TestPath as RadiusTestPath
from radius_testing.domain import TestRunPlan as RadiusTestRunPlan
from radius_testing.domain import TestRunStatus as RadiusTestRunStatus
from radius_testing.infrastructure import ContainerSandboxRunner, SandboxConfig

SANDBOX_TEST_IMAGE = os.environ.get("RADIUS_SANDBOX_TEST_IMAGE", "radius-sandbox-test:latest")
REQUIRE = os.environ.get("RADIUS_REQUIRE_SANDBOX_TESTS") == "true"

# Tight limits so that a failure of containment is bounded even in the worst case.
PIDS = 64
MEMORY = "128m"
TMPFS = "16m"
FSIZE = 1024 * 1024

FAKE_SECRETS = {
    "DATABASE_URL": "postgresql+psycopg://radius:SUPERSECRETDB@db:5432/radius",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----SUPERSECRETKEY",
}


def _docker_ready() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        done = subprocess.run(
            [docker, "image", "inspect", SANDBOX_TEST_IMAGE],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


_READY = _docker_ready()
if REQUIRE and not _READY:
    raise RuntimeError(
        f"RADIUS_REQUIRE_SANDBOX_TESTS=true but docker or {SANDBOX_TEST_IMAGE!r} is unavailable"
    )

pytestmark = [
    pytest.mark.sandbox_adversarial,
    pytest.mark.skipif(
        not _READY,
        reason=f"docker daemon or image {SANDBOX_TEST_IMAGE!r} unavailable",
    ),
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _config(**overrides) -> SandboxConfig:
    kwargs = {
        "image": SANDBOX_TEST_IMAGE,
        "memory": MEMORY,
        "cpus": "0.5",
        "pids_limit": PIDS,
        "tmpfs_size": TMPFS,
        "timeout_seconds": 60,
        "max_file_size_bytes": FSIZE,
        "max_output_bytes": 1024 * 1024,
    }
    kwargs.update(overrides)
    return SandboxConfig(**kwargs)


def _repo(tmp_path: Path, payload: str) -> Path:
    repo = tmp_path / "cache" / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "payload.py").write_text(textwrap.dedent(payload))
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[http]\n\textraheader = AUTHORIZATION: SUPERSECRETGIT\n")
    return repo


def _plan() -> RadiusTestRunPlan:
    return RadiusTestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=(
            RadiusTestCase(
                id=uuid4(),
                name=RadiusTestName("payload"),
                path=RadiusTestPath("tests/payload.py"),
                framework=RadiusTestFramework.PYTEST,
            ),
        ),
        command_plan=(("python", ("tests/payload.py",)),),
    )


def _container_exists(name: str) -> bool:
    done = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(done.stdout.strip())


def _run_checked(tmp_path: Path, repo: Path, monkeypatch, **config):
    """Run the sandbox on ``repo`` and assert nothing is left behind afterwards.

    Records exactly the container names and temp dirs *this* run created, so the
    checks stay valid when other sandbox runs share the docker daemon.
    """

    names: list[str] = []
    workdirs: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        workdirs.append(Path(path))
        return path

    def recording_launcher(argv, **kwargs):
        names.append(argv[argv.index("--name") + 1])
        return subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv list, no shell

    monkeypatch.setattr(tempfile, "mkdtemp", recording_mkdtemp)
    started = time.monotonic()
    result = ContainerSandboxRunner(_config(**config), launcher=recording_launcher).run(
        _plan(), repo
    )
    elapsed = time.monotonic() - started
    monkeypatch.undo()
    assert names, "no container was started"
    assert workdirs and not any(w.exists() for w in workdirs), "workspace was not removed"
    assert not any(_container_exists(n) for n in names), "container left behind"
    # The (host) repository checkout was never written to.
    assert sorted(p.name for p in repo.iterdir()) == [".git", "tests"]
    assert not [p.name for p in (repo / "tests").iterdir() if p.name != "payload.py"
                and not p.name.startswith("link_")]
    return result, elapsed


@pytest.fixture
def run(tmp_path: Path, monkeypatch):
    def _run(payload: str, **config):
        return _run_checked(tmp_path, _repo(tmp_path, payload), monkeypatch, **config)

    return _run


def _assert_denied(result, *markers: str) -> None:
    assert "BREACH" not in result.output, result.output
    for marker in markers:
        assert f"{marker}: DENIED" in result.output, result.output
    assert result.status == RadiusTestRunStatus.PASSED, result.output


# --------------------------------------------------------------------------
# resource attacks: contained and classified by the runner
# --------------------------------------------------------------------------


def test_infinite_loop_is_killed_by_timeout(run) -> None:
    result, elapsed = run(
        """
        while True:
            pass
        """,
        timeout_seconds=5,
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "timed out after 5 seconds" in result.output
    assert elapsed < 40


def test_fork_bomb_is_contained_by_pids_limit_and_timeout(run) -> None:
    result, elapsed = run(
        """
        import os, time
        while True:          # classic fork bomb; the kernel pids cgroup must stop it
            try:
                os.fork()
            except OSError:
                time.sleep(0.01)
        """,
        timeout_seconds=10,
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "timed out after 10 seconds" in result.output
    assert elapsed < 60


def test_pids_limit_denies_fork_beyond_cap(run) -> None:
    result, _ = run(
        f"""
        import os, time
        children = 0
        denied = False
        for _ in range({PIDS * 4}):
            try:
                pid = os.fork()
            except OSError:
                denied = True
                break
            if pid == 0:
                time.sleep(20)
                os._exit(0)
            children += 1
        print("FORKED", children, "pids_limit", {PIDS})
        if not denied or children > {PIDS}:
            print("BREACH: forked", children)
        else:
            print("PIDS: DENIED")
        os._exit(0)           # container teardown reaps the sleeping children
        """,
    )

    _assert_denied(result, "PIDS")


def test_memory_bomb_is_oom_killed_and_reported_as_error(run) -> None:
    result, _ = run(
        """
        hog = []
        while True:
            hog.append(bytearray(8 * 1024 * 1024))
            for chunk in hog[-1:]:
                chunk[::4096] = b"\\x01" * len(chunk[::4096])   # touch every page
        """,
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "SIGKILL" in result.output


def test_disk_fill_is_capped_by_tmpfs_and_file_size_limit(run) -> None:
    result, _ = run(
        """
        import os, signal
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        chunk = b"x" * 65536
        # many small files fill the 16m tmpfs; a single file is capped by ulimit fsize
        written = 0
        full = False
        for index in range(400):
            try:
                with open(f"/tmp/fill{index}", "wb") as handle:
                    for _ in range(12):
                        handle.write(chunk)
                        written += len(chunk)
            except OSError:
                full = True
                break
        single_capped = False
        try:
            with open("/tmp/one-big-file", "wb") as handle:
                for _ in range(64):
                    handle.write(chunk)
                    handle.flush()
        except OSError:
            single_capped = True
        print("WRITTEN", written)
        print("TMPFS: DENIED" if full and written <= 16 * 1024 * 1024 else "BREACH: tmpfs")
        print("FSIZE: DENIED" if single_capped else "BREACH: fsize")
        """,
    )

    _assert_denied(result, "TMPFS", "FSIZE")


def test_output_flood_is_capped_and_container_killed(run) -> None:
    result, elapsed = run(
        """
        import sys
        line = "A" * 1023 + "\\n"
        while True:
            sys.stdout.write(line * 1024)
            sys.stdout.flush()
        """,
        max_output_bytes=512 * 1024,
        timeout_seconds=60,
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "output exceeded" in result.output
    assert len(result.output.encode()) < 2 * 1024 * 1024  # retained output is bounded
    assert elapsed < 40


# --------------------------------------------------------------------------
# confinement: network, secrets, filesystem, /proc, privileges
# --------------------------------------------------------------------------


def test_network_egress_is_denied(run) -> None:
    result, _ = run(
        """
        import os, socket
        targets = [("1.1.1.1", 53), ("8.8.8.8", 53), ("169.254.169.254", 80), ("10.0.0.1", 80)]
        reached = []
        for host, port in targets:
            try:
                socket.create_connection((host, port), timeout=3).close()
                reached.append(host)
            except OSError:
                pass
        try:
            socket.getaddrinfo("example.com", 80)
            reached.append("dns")
        except OSError:
            pass
        interfaces = sorted(os.listdir("/sys/class/net"))
        print("INTERFACES", interfaces)
        print("NETWORK: DENIED" if not reached and interfaces == ["lo"] else f"BREACH: {reached}")
        """,
    )

    _assert_denied(result, "NETWORK")


def test_host_environment_and_secrets_are_not_visible(run, monkeypatch) -> None:
    for key, value in FAKE_SECRETS.items():
        monkeypatch.setenv(key, value)
    result, _ = run(
        """
        import glob, os
        needle = b"SUPER" + b"SECRET"          # not a literal, so this file never matches itself
        leaks = []
        for key in os.environ:
            if "SECRET" in os.environ[key].upper() or key in ("DATABASE_URL", "GITHUB_APP_PRIVATE_KEY"):
                leaks.append(("environ", key))
        for path in glob.glob("/proc/[0-9]*/environ"):
            try:
                if needle in open(path, "rb").read():
                    leaks.append(("proc", path))
            except OSError:
                pass
        for root in ("/workspace", "/"):
            for dirpath, _dirs, files in os.walk(root):
                if dirpath.startswith(("/proc", "/sys", "/dev", "/usr", "/lib")):
                    continue
                for name in files:
                    try:
                        if needle in open(os.path.join(dirpath, name), "rb").read(65536):
                            leaks.append(("file", os.path.join(dirpath, name)))
                    except OSError:
                        pass
        print("ENV: DENIED" if not leaks else f"BREACH: {leaks}")
        """,
    )

    _assert_denied(result, "ENV")
    assert "SUPERSECRET" not in result.output


def test_writes_outside_workspace_and_to_rootfs_are_denied(run) -> None:
    result, _ = run(
        """
        import os
        escaped = []
        for path in ("/workspace/pwned", "/workspace/tests/pwned", "/pwned", "/etc/pwned",
                     "/usr/pwned", "/root/pwned", "/results-evil", "/home/pwned"):
            try:
                open(path, "w").write("x")
                escaped.append(path)
            except OSError:
                pass
        try:
            os.mkdir("/workspace/newdir")
            escaped.append("mkdir")
        except OSError:
            pass
        try:
            os.remove("/workspace/tests/payload.py")
            escaped.append("delete-payload")
        except OSError:
            pass
        open("/tmp/ok", "w").write("tmpfs is writable")      # the only writable area
        print("WRITE: DENIED" if not escaped else f"BREACH: {escaped}")
        """,
    )

    _assert_denied(result, "WRITE")


def test_symlink_escape_cannot_read_or_write_host_files(tmp_path: Path, monkeypatch) -> None:
    secret = tmp_path / "host-secret.txt"
    secret.write_text("SUPERSECRET-HOST-FILE")
    repo = _repo(
        tmp_path,
        """
        import os
        leaks = []
        for link in sorted(os.listdir("/workspace/tests")):
            if not link.startswith("link_"):
                continue
            target = os.path.join("/workspace/tests", link)
            try:
                if b"SUPERSECRET" in open(target, "rb").read():
                    leaks.append(link)
            except OSError:
                pass
        for path in ("/workspace/tests/link_up/pwned", "/workspace/tests/link_abs/pwned"):
            try:
                open(path, "w").write("x")
                leaks.append(path)
            except OSError:
                pass
        try:
            os.symlink("/etc/passwd", "/workspace/tests/link_new")
            leaks.append("created link")
        except OSError:
            pass
        print("SYMLINK: DENIED" if not leaks else f"BREACH: {leaks}")
        """,
    )
    try:
        os.symlink(secret, repo / "tests" / "link_abs")  # absolute host path
        os.symlink(secret, repo / "tests" / "link_file")
        os.symlink("../../../../../../../../etc", repo / "tests" / "link_up")
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symlinks (needs privilege on this OS)")

    result, _ = _run_checked(tmp_path, repo, monkeypatch)

    _assert_denied(result, "SYMLINK")
    assert "SUPERSECRET" not in result.output
    assert secret.read_text() == "SUPERSECRET-HOST-FILE"
    assert not (repo / "tests" / "pwned").exists()


def test_proc_and_sys_access_cannot_escape_or_tamper(run) -> None:
    result, _ = run(
        """
        import os
        breaches = []
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
        if len(pids) > 20:
            breaches.append(f"host-like pid namespace: {len(pids)} pids")
        for path, data in (("/proc/sys/kernel/hostname", "pwned"),
                           ("/proc/sys/kernel/core_pattern", "|/tmp/x"),
                           ("/proc/sysrq-trigger", "b"),
                           ("/sys/kernel/uevent_helper", "/tmp/x"),
                           ("/proc/sys/vm/drop_caches", "3")):
            try:
                open(path, "w").write(data)
                breaches.append(f"wrote {path}")
            except OSError:
                pass
        for path in ("/proc/kcore", "/proc/kmsg", "/proc/1/mem", "/proc/1/root/etc/shadow"):
            try:
                # runtimes mask these paths with /dev/null: an empty read is containment
                if open(path, "rb").read(16):
                    breaches.append(f"read {path}")
            except OSError:
                pass
        try:
            os.listdir("/proc/1/root/workspace")     # own container only, never the host
        except OSError:
            pass
        print("PROC: DENIED" if not breaches else f"BREACH: {breaches}")
        """,
    )

    _assert_denied(result, "PROC")


def test_privileges_are_dropped(run) -> None:
    result, _ = run(
        """
        import ctypes, os
        status = dict(
            line.split(":\\t", 1) for line in open("/proc/self/status").read().splitlines()
            if ":\\t" in line
        )
        problems = []
        if os.getuid() != 65534 or os.getgid() != 65534:
            problems.append("not nobody")
        if int(status["CapEff"], 16) or int(status["CapBnd"], 16):
            problems.append("capabilities present " + status["CapEff"] + status["CapBnd"])
        if status["NoNewPrivs"].strip() != "1":
            problems.append("no_new_privs off")
        if status["Seccomp"].strip() != "2":
            problems.append("seccomp filter off")
        libc = ctypes.CDLL(None, use_errno=True)
        # privileged syscalls must fail: mount, chroot, setuid(0), unshare(CLONE_NEWUSER)
        if libc.mount(b"none", b"/tmp", b"tmpfs", 0, None) == 0:
            problems.append("mount succeeded")
        if libc.chroot(b"/tmp") == 0:
            problems.append("chroot succeeded")
        if libc.setuid(0) == 0:
            problems.append("setuid(0) succeeded")
        if libc.unshare(0x10000000) == 0:
            problems.append("unshare(NEWUSER) succeeded")
        print("PRIV: DENIED" if not problems else f"BREACH: {problems}")
        """,
    )

    _assert_denied(result, "PRIV")
