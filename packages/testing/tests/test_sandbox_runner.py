"""ContainerSandboxRunner tests.

Unit tests inject a fake process launcher, so they need no container runtime.
The integration tests at the bottom run against a real docker daemon and skip
when one (or the test image) is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
from radius_testing.infrastructure.sandbox_runner import (
    CONTAINER_JUNIT_PATH,
    SANDBOX_ENV,
    build_container_argv,
    sandbox_command,
)

FAKE_SECRETS = {
    "DATABASE_URL": "postgresql+psycopg://radius:SUPERSECRETDB@db:5432/radius",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----SUPERSECRETKEY",
    "RADIUS_GITHUB_WEBHOOK_SECRET": "SUPERSECRETHOOK",
}

JUNIT_OK = (
    b'<?xml version="1.0"?><testsuites><testsuite name="s" tests="2" '
    b'failures="0" errors="0" skipped="0">'
    b'<testcase classname="t" name="a"/><testcase classname="t" name="b"/>'
    b"</testsuite></testsuites>"
)


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in FAKE_SECRETS.items():
        monkeypatch.setenv(key, value)


def _plan(command_plan, paths=("tests/test_ok.py",)) -> RadiusTestRunPlan:
    return RadiusTestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=tuple(
            RadiusTestCase(
                id=uuid4(),
                name=RadiusTestName(Path(p).stem),
                path=RadiusTestPath(p),
                framework=RadiusTestFramework.PYTEST,
            )
            for p in paths
        ),
        command_plan=command_plan,
    )


PYTEST_PLAN = (("python", ("-m", "pytest", "tests/test_ok.py")),)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "cache" / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[http]\n\textraheader = AUTHORIZATION: x\n")
    return repo


def _argv(**overrides) -> list[str]:
    kwargs = {
        "runtime_path": "/usr/bin/docker",
        "container_name": "radius-sbx-abc123",
        "workspace_dir": Path("/tmp/radius-sandbox-x/workspace"),
        "results_dir": Path("/tmp/radius-sandbox-x/cmd-0/results"),
        "command": ["python", "-m", "pytest", "tests/test_ok.py"],
    }
    kwargs.update(overrides)
    return build_container_argv(SandboxConfig(), **kwargs)


def _pairs(argv: list[str]) -> set[tuple[str, str]]:
    return set(zip(argv, argv[1:], strict=False))


# --------------------------------------------------------------------------
# Pure command construction
# --------------------------------------------------------------------------


def test_container_argv_contains_every_isolation_flag() -> None:
    argv = _argv()
    pairs = _pairs(argv)

    assert argv[:3] == ["/usr/bin/docker", "run", "--rm"]
    assert "--read-only" in argv
    for flag, value in [
        ("--network", "none"),
        ("--ipc", "none"),
        ("--pull", "never"),
        ("--user", "65534:65534"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--pids-limit", "256"),
        ("--memory", "1g"),
        ("--memory-swap", "1g"),
        ("--cpus", "1.0"),
        ("--workdir", "/workspace"),
        ("--name", "radius-sbx-abc123"),
    ]:
        assert (flag, value) in pairs, flag
    assert ("--tmpfs", "/tmp:rw,nosuid,nodev,size=256m") in pairs
    assert (
        "--mount",
        "type=bind,source=/tmp/radius-sandbox-x/workspace,target=/workspace,readonly",
    ) in pairs
    # The results mount is the only writable host mount.
    mounts = [value for flag, value in pairs if flag == "--mount"]
    writable = [m for m in mounts if not m.endswith(",readonly")]
    assert writable == [
        "type=bind,source=/tmp/radius-sandbox-x/cmd-0/results,target=/results"
    ]
    assert "--privileged" not in argv
    assert not any(a.startswith("--network=") or a == "host" for a in argv)


def test_container_argv_never_carries_host_secrets(secret_env) -> None:
    argv = _argv()
    joined = "\0".join(argv)

    for key, value in FAKE_SECRETS.items():
        assert key not in joined
        assert value not in joined
    env_values = [value for flag, value in zip(argv, argv[1:], strict=False) if flag == "--env"]
    # Only the fixed allowlist, always KEY=VALUE (a bare KEY would forward host env).
    assert env_values == [f"{k}={v}" for k, v in SANDBOX_ENV.items()]
    assert all("=" in value for value in env_values)
    assert "--env-file" not in argv and "-e" not in argv


def test_container_argv_places_untrusted_command_after_image() -> None:
    argv = _argv(command=["python", "--privileged", "-v", "/:/host"])
    image_index = argv.index("python:3.12-slim")
    assert argv[image_index + 1 :] == ["python", "--privileged", "-v", "/:/host"]
    assert "--privileged" not in argv[:image_index]


def test_container_argv_reflects_config_limits() -> None:
    config = SandboxConfig(
        image="registry.example/radius/py:1",
        runtime="podman",
        memory="512m",
        cpus="0.5",
        pids_limit=64,
        tmpfs_size="64m",
    )
    argv = build_container_argv(
        config,
        runtime_path="/usr/bin/podman",
        container_name="radius-sbx-1",
        workspace_dir=Path("/w"),
        results_dir=Path("/r"),
        command=["python", "x.py"],
    )
    pairs = _pairs(argv)
    assert {("--memory", "512m"), ("--cpus", "0.5"), ("--pids-limit", "64")} <= pairs
    assert ("--tmpfs", "/tmp:rw,nosuid,nodev,size=64m") in pairs
    assert argv[0] == "/usr/bin/podman"
    assert argv[-3:] == ["registry.example/radius/py:1", "python", "x.py"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"runtime": "bash"},
        {"image": "--privileged"},
        {"image": ""},
        {"memory": "1g --privileged"},
        {"cpus": "0"},
        {"pids_limit": 0},
        {"timeout_seconds": 0},
    ],
)
def test_sandbox_config_rejects_unsafe_values(kwargs) -> None:
    with pytest.raises(ValueError):
        SandboxConfig(**kwargs)


def test_pytest_command_writes_junit_only_to_results_mount() -> None:
    argv, is_pytest = sandbox_command("python", ("-m", "pytest", "tests/test_ok.py"))
    assert is_pytest
    assert f"--junitxml={CONTAINER_JUNIT_PATH}" in argv
    assert CONTAINER_JUNIT_PATH.startswith("/results/")
    assert sandbox_command("npx", ("--no-install", "jest", "a.test.js")) == (
        ["npx", "--no-install", "jest", "a.test.js"],
        False,
    )


# --------------------------------------------------------------------------
# Runner behaviour with an injected fake launcher
# --------------------------------------------------------------------------


class FakeProcess:
    def __init__(self, returncode: int = 0, hang: bool = False) -> None:
        self.returncode = returncode
        self.hang = hang
        self.killed = False
        self.wait_calls = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired(cmd="docker run", timeout=timeout or 0)
        return -9 if self.killed else self.returncode

    def kill(self) -> None:
        self.killed = True


class FakeLauncher:
    """Records launches and simulates the container writing to the results mount."""

    def __init__(self, process: FakeProcess, junit: bytes | None = JUNIT_OK) -> None:
        self.process = process
        self.junit = junit
        self.calls: list[dict] = []
        self.workspace_seen: dict = {}

    def __call__(self, argv, **kwargs):
        mounts = {
            value.split("target=")[1].split(",")[0]: Path(
                value.split("source=")[1].split(",")[0]
            )
            for flag, value in zip(argv, argv[1:], strict=False)
            if flag == "--mount"
        }
        workspace = mounts["/workspace"]
        self.workspace_seen = {
            "path": workspace,
            "has_git": (workspace / ".git").exists(),
            "has_test": (workspace / "tests" / "test_ok.py").is_file(),
            "secret_link_is_link": (workspace / "leak").is_symlink(),
        }
        self.calls.append({"argv": argv, **kwargs})
        if self.junit is not None:
            (mounts["/results"] / "junit.xml").write_bytes(self.junit)
        kwargs["stdout"].write(b"container stdout\n")
        return self.process


class AuxRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)


def _runner(launcher, aux=None, which=lambda name: "/usr/bin/docker", **config):
    return ContainerSandboxRunner(
        SandboxConfig(**config),
        launcher=launcher,
        aux_runner=aux or AuxRecorder(),
        which=which,
    )


def test_missing_runtime_is_error_never_pass(tmp_path: Path) -> None:
    launcher = FakeLauncher(FakeProcess())
    result = _runner(launcher, which=lambda name: None).run(_plan(PYTEST_PLAN), _repo(tmp_path))

    assert result.status == RadiusTestRunStatus.ERROR
    assert (result.total_tests, result.passed) == (0, 0)
    assert "container runtime 'docker' not found" in result.output
    assert launcher.calls == []


def test_runtime_binary_vanishing_at_launch_is_error(tmp_path: Path) -> None:
    def launcher(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    result = _runner(launcher).run(_plan(PYTEST_PLAN), _repo(tmp_path))

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "not found" in result.output


def test_successful_pytest_run_uses_junit_from_results_mount(
    tmp_path: Path, secret_env
) -> None:
    launcher = FakeLauncher(FakeProcess(returncode=0))
    result = _runner(launcher).run(_plan(PYTEST_PLAN), _repo(tmp_path))

    assert result.status == RadiusTestRunStatus.PASSED
    assert (result.total_tests, result.passed, result.failed) == (2, 2, 0)
    call = launcher.calls[0]
    # The runtime CLI process itself gets no worker secrets either.
    for key, value in FAKE_SECRETS.items():
        assert key not in call["env"]
        assert value not in "\0".join(call["argv"])
        assert value not in "\0".join(call["env"].values())


def test_snapshot_is_a_fresh_copy_without_git_and_is_cleaned_up(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "worker-secret.txt"
    outside.write_text("SUPERSECRET")
    (repo / "leak").symlink_to(outside)
    before = sorted(str(p.relative_to(repo)) for p in repo.rglob("*"))
    launcher = FakeLauncher(FakeProcess(returncode=0))

    _runner(launcher).run(_plan(PYTEST_PLAN), repo)

    seen = launcher.workspace_seen
    assert seen["has_test"] is True
    assert seen["has_git"] is False  # .git (and any clone credentials) never mounted
    assert seen["secret_link_is_link"] is True  # copied as a link, never followed
    assert not str(seen["path"]).startswith(str(repo))
    assert not seen["path"].exists()  # temp snapshot removed in finally
    assert not seen["path"].parent.exists()
    assert sorted(str(p.relative_to(repo)) for p in repo.rglob("*")) == before


def test_temp_dir_is_cleaned_up_even_when_launcher_crashes(tmp_path: Path) -> None:
    seen: dict = {}

    def launcher(argv, **kwargs):
        mount = next(v for v in argv if v.startswith("type=bind") and "readonly" in v)
        seen["workspace"] = Path(mount.split("source=")[1].split(",")[0])
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _runner(launcher).run(_plan(PYTEST_PLAN), _repo(tmp_path))

    assert not seen["workspace"].parent.exists()


def test_timeout_kills_and_removes_container_and_reports_error(tmp_path: Path) -> None:
    process = FakeProcess(hang=True)
    launcher = FakeLauncher(process)
    aux = AuxRecorder()

    result = _runner(launcher, aux=aux, timeout_seconds=7).run(
        _plan(PYTEST_PLAN), _repo(tmp_path)
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "timed out after 7 seconds" in result.output
    name = launcher.calls[0]["argv"][launcher.calls[0]["argv"].index("--name") + 1]
    assert ["/usr/bin/docker", "kill", name] in aux.calls
    assert ["/usr/bin/docker", "rm", "-f", name] in aux.calls
    assert aux.calls.index(["/usr/bin/docker", "kill", name]) < aux.calls.index(
        ["/usr/bin/docker", "rm", "-f", name]
    )
    assert process.killed is True


@pytest.mark.parametrize("code", [125, 126, 127])
def test_runtime_exit_codes_are_errors_not_failures(tmp_path: Path, code: int) -> None:
    launcher = FakeLauncher(FakeProcess(returncode=code), junit=None)
    result = _runner(launcher).run(
        _plan((("npx", ("--no-install", "jest", "a.test.js")),), ("a.test.js",)),
        _repo(tmp_path),
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert (result.passed, result.failed) == (0, 0)


def test_pytest_without_junit_report_is_error(tmp_path: Path) -> None:
    launcher = FakeLauncher(FakeProcess(returncode=0), junit=None)
    result = _runner(launcher).run(_plan(PYTEST_PLAN), _repo(tmp_path))

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0


# --------------------------------------------------------------------------
# Real container runtime (skipped when docker or the test image is missing)
# --------------------------------------------------------------------------

SANDBOX_TEST_IMAGE = os.environ.get("RADIUS_SANDBOX_TEST_IMAGE", "radius-sandbox-test:latest")


def _docker_ready() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        info = subprocess.run(
            [docker, "image", "inspect", SANDBOX_TEST_IMAGE],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return info.returncode == 0


if os.environ.get("RADIUS_REQUIRE_SANDBOX_TESTS") == "true" and not _docker_ready():
    # CI builds the image; a silent skip there would hide isolation regressions.
    raise RuntimeError(
        f"RADIUS_REQUIRE_SANDBOX_TESTS=true but docker or {SANDBOX_TEST_IMAGE!r} is unavailable"
    )

requires_docker = pytest.mark.skipif(
    not _docker_ready(),
    reason=(
        f"docker daemon or image {SANDBOX_TEST_IMAGE!r} unavailable "
        "(build: FROM python:3.12-slim + pip install pytest)"
    ),
)

ADVERSARIAL_PROBE = r'''
import os, socket, sys
problems = []
if os.getuid() != 65534:
    problems.append(f"uid={os.getuid()}")
for key in ("DATABASE_URL", "GITHUB_APP_PRIVATE_KEY"):
    if key in os.environ:
        problems.append(f"env leak {key}")
try:
    data = open(f"/proc/{os.getppid()}/environ", "rb").read()
    if b"SUPERSECRET" in data:
        problems.append("proc environ leak")
except OSError:
    pass
for path in ("/workspace/pwned", "/pwned"):
    try:
        open(path, "w").write("x")
        problems.append(f"wrote {path}")
    except OSError:
        pass
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    problems.append("network egress")
except OSError:
    pass
if os.path.exists("/workspace/.git"):
    problems.append(".git mounted")
open("/tmp/scratch", "w").write("tmpfs ok")
print("PROBLEMS:", problems)
sys.exit(1 if problems else 0)
'''


@requires_docker
def test_real_container_enforces_isolation(tmp_path: Path, secret_env) -> None:
    repo = _repo(tmp_path)
    (repo / "tests" / "probe.py").write_text(ADVERSARIAL_PROBE)
    runner = ContainerSandboxRunner(SandboxConfig(image=SANDBOX_TEST_IMAGE, timeout_seconds=120))

    result = runner.run(
        _plan((("python", ("tests/probe.py",)),), ("tests/probe.py",)), repo
    )

    assert "PROBLEMS: []" in result.output, result.output
    assert result.status == RadiusTestRunStatus.PASSED
    assert not (repo / "pwned").exists()
    assert sorted(p.name for p in repo.iterdir()) == [".git", "tests"]


@requires_docker
def test_real_container_runs_pytest_and_reports_junit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tests" / "test_mix.py").write_text(
        "import pytest\n"
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert False\n"
        "@pytest.mark.skip\ndef test_c():\n    pass\n"
    )
    runner = ContainerSandboxRunner(SandboxConfig(image=SANDBOX_TEST_IMAGE, timeout_seconds=120))

    result = runner.run(
        _plan((("python", ("-m", "pytest", "tests/test_mix.py")),), ("tests/test_mix.py",)),
        repo,
    )

    assert result.status == RadiusTestRunStatus.FAILED, result.output
    assert (result.total_tests, result.passed, result.failed, result.skipped) == (3, 1, 1, 1)


@requires_docker
def test_real_container_timeout_kills_container(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tests" / "test_hang.py").write_text(
        "import time\ndef test_hang():\n    time.sleep(120)\n"
    )
    runner = ContainerSandboxRunner(SandboxConfig(image=SANDBOX_TEST_IMAGE, timeout_seconds=5))

    result = runner.run(
        _plan((("python", ("-m", "pytest", "tests/test_hang.py")),), ("tests/test_hang.py",)),
        repo,
    )

    assert result.status == RadiusTestRunStatus.ERROR
    assert "timed out after 5 seconds" in result.output
    leftover = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "name=radius-sbx-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert leftover.stdout.strip() == ""
