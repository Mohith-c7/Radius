"""Container-sandboxed test runner.

Runs each planned test command in a throw-away container so that
pull-request-controlled code never shares a uid, PID namespace, network,
filesystem, or environment with the worker that holds ``DATABASE_URL`` and the
GitHub App private key.

Isolation applied to every command (see ``build_container_argv``):

* ``--rm`` plus an explicit ``rm -f`` in ``finally``; unique container name.
* ``--network none``: no egress to the database, GitHub, metadata endpoints,
  or the internet. The image must already contain the test dependencies.
* ``--read-only`` root filesystem; a size-capped ``tmpfs`` on ``/tmp``.
* Workspace = a **fresh copy** of the checkout (``.git`` excluded, symlinks
  copied as links and never followed), bind-mounted read-only. The shared
  repository cache is never mounted and so can never be mutated.
* The only writable host mount is a per-command results directory
  (JUnit XML).
* ``--user 65534:65534`` (nobody), ``--cap-drop ALL``,
  ``--security-opt no-new-privileges``, ``--ipc none``.
* ``--pids-limit``, ``--memory`` (+ equal ``--memory-swap``), ``--cpus``,
  and ``--ulimit`` for open files, single-file size and core dumps.
* The runtime's default seccomp profile stays on (``unconfined`` is rejected);
  an operator may supply a stricter custom profile.
* Output is capped: a watchdog kills the container if either stream grows past
  ``max_output_bytes`` on the host, and only the first 500 KB is retained.
* Fail closed: ``check_ready`` / every ``run`` verifies the runtime, daemon, image
  and seccomp profile *before* anything is executed; otherwise ``ERROR``.
* ``--pull never``: images are provisioned by operators, never fetched at
  analysis time.
* Environment: only the fixed ``SANDBOX_ENV`` allowlist, always passed as
  ``KEY=VALUE``. Host environment variables are never forwarded.
* Wall-clock timeout; on expiry the container is ``kill``-ed and removed.

Failure semantics match ``SubprocessTestRunner``: a missing container runtime,
a runtime/daemon failure, a timeout, or an interrupted session yields
``TestRunStatus.ERROR`` -- never ``PASSED``.

This is a container boundary, not a VM boundary: a kernel exploit escapes it.
For hostile multi-tenant workloads run the runtime under gVisor
(``--runtime runsc``) or a microVM; see ``docs/security/EXECUTION_ISOLATION.md``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from radius_shared.observability.metrics import record_sandbox_kill

from radius_testing.domain.entities import CaseOutcome, TestRunPlan, TestRunResult
from radius_testing.domain.flakiness import RerunPolicy
from radius_testing.infrastructure.junit_parser import JUnitReportParser
from radius_testing.infrastructure.result_matching import report_cases
from radius_testing.infrastructure.subprocess_runner import (
    _CommandOutcome,
    build_run_result,
    exit_code_outcome,
    planned_test_files,
    pytest_outcome,
)

LOGGER = logging.getLogger(__name__)

SUPPORTED_RUNTIMES = frozenset({"docker", "podman"})
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_RESULTS = "/results"
CONTAINER_JUNIT_PATH = f"{CONTAINER_RESULTS}/junit.xml"
NOBODY_USER = "65534:65534"
# Fixed, explicit environment for the sandboxed process. Nothing else is passed.
SANDBOX_ENV: Mapping[str, str] = {
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "LANG": "C.UTF-8",
    "CI": "true",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "NO_COLOR": "1",
}
# Exit codes produced by the container runtime itself (not by the test command).
RUNTIME_EXIT_CODES = {
    125: "container runtime failed to start the container",
    126: "test command in the sandbox image could not be invoked",
    127: "test command was not found in the sandbox image",
}
# 128 + signal: the sandboxed process was terminated by a resource limit or the
# kernel. Reported as ERROR (contained), never as a test failure or pass.
CONTAINED_EXIT_CODES = {
    137: "killed by SIGKILL (memory limit / OOM kill or forced termination)",
    152: "killed by SIGXCPU (CPU time limit)",
    153: "killed by SIGXFSZ (file size limit)",
}
DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
_WATCHDOG_INTERVAL_SECONDS = 0.2
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[kmg]?$", re.IGNORECASE)
_CPUS_RE = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?)$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]*$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Operator-controlled sandbox limits."""

    image: str = "python:3.12-slim"
    runtime: str = "docker"
    memory: str = "1g"
    cpus: str = "1.0"
    pids_limit: int = 256
    tmpfs_size: str = "256m"
    timeout_seconds: int = 600
    nofile_limit: int = 1024
    max_file_size_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    seccomp_profile: str | None = None

    def __post_init__(self) -> None:
        if Path(self.runtime).name not in SUPPORTED_RUNTIMES:
            msg = f"unsupported container runtime {self.runtime!r}; use docker or podman"
            raise ValueError(msg)
        if not _IMAGE_RE.match(self.image):
            raise ValueError(f"invalid sandbox image reference {self.image!r}")
        for label, value in (("memory", self.memory), ("tmpfs_size", self.tmpfs_size)):
            if not _MEMORY_RE.match(value):
                raise ValueError(f"invalid sandbox {label} {value!r}")
        if not _CPUS_RE.match(self.cpus) or float(self.cpus) <= 0:
            raise ValueError(f"invalid sandbox cpus {self.cpus!r}")
        if self.pids_limit <= 0:
            raise ValueError("sandbox pids_limit must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("sandbox timeout_seconds must be positive")
        for label, number in (
            ("nofile_limit", self.nofile_limit),
            ("max_file_size_bytes", self.max_file_size_bytes),
            ("max_output_bytes", self.max_output_bytes),
        ):
            if number <= 0:
                raise ValueError(f"sandbox {label} must be positive")
        if self.seccomp_profile is not None and (
            not self.seccomp_profile.strip()
            or self.seccomp_profile.strip().lower() == "unconfined"
            or "," in self.seccomp_profile
        ):
            raise ValueError("sandbox seccomp_profile must be a profile file path, not unconfined")


def build_container_argv(
    config: SandboxConfig,
    *,
    runtime_path: str,
    container_name: str,
    workspace_dir: Path,
    results_dir: Path,
    command: Sequence[str],
) -> list[str]:
    """Return the full ``<runtime> run ...`` argv for one sandboxed command.

    Pure function: no I/O, no environment access. Every isolation flag is
    unconditional; the only inputs are operator config, two host paths
    created by the runner, and the planned command (placed after the image,
    so it can never be parsed as a runtime flag).
    """

    if not _NAME_RE.match(container_name):
        raise ValueError(f"invalid container name {container_name!r}")
    if not command:
        raise ValueError("sandbox command must not be empty")
    argv = [
        runtime_path,
        "run",
        "--rm",
        "--name",
        container_name,
        "--pull",
        "never",
        "--network",
        "none",
        "--ipc",
        "none",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,size={config.tmpfs_size}",
        "--user",
        NOBODY_USER,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if config.seccomp_profile:
        # Replaces (never disables) the runtime's default profile; read client-side.
        argv.extend(["--security-opt", f"seccomp={config.seccomp_profile}"])
    argv += [
        "--ulimit",
        f"nofile={config.nofile_limit}:{config.nofile_limit}",
        "--ulimit",
        f"fsize={config.max_file_size_bytes}:{config.max_file_size_bytes}",
        "--ulimit",
        "core=0:0",
        "--pids-limit",
        str(config.pids_limit),
        "--memory",
        config.memory,
        "--memory-swap",
        config.memory,
        "--cpus",
        config.cpus,
        "--mount",
        f"type=bind,source={workspace_dir},target={CONTAINER_WORKSPACE},readonly",
        "--mount",
        f"type=bind,source={results_dir},target={CONTAINER_RESULTS}",
        "--workdir",
        CONTAINER_WORKSPACE,
    ]
    for key, value in SANDBOX_ENV.items():
        # Always KEY=VALUE: a bare ``--env KEY`` would forward the host value.
        argv.extend(["--env", f"{key}={value}"])
    argv.append(config.image)
    argv.extend(command)
    return argv


def sandbox_command(command: str, args: tuple[str, ...]) -> tuple[list[str], bool]:
    """Return the in-container argv for a planned command and whether it is pytest."""

    is_pytest = command == "python" and args[:2] == ("-m", "pytest")
    if is_pytest:
        return [
            "python",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--junitxml={CONTAINER_JUNIT_PATH}",
            *args[2:],
        ], True
    return [command, *args], False


class SandboxUnavailableError(RuntimeError):
    """The sandbox cannot be used safely; execution must not proceed."""


class _Process(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


ProcessLauncher = Callable[..., _Process]
AuxRunner = Callable[..., object]


@dataclass(slots=True)
class _Execution:
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    failure: str | None = None


class ContainerSandboxRunner:
    """Execute planned test commands inside an isolated, ephemeral container."""

    MAX_OUTPUT_SIZE = 500 * 1024  # 500KB

    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        launcher: ProcessLauncher | None = None,
        aux_runner: AuxRunner | None = None,
        which: Callable[[str], str | None] | None = None,
        probe: AuxRunner | None = None,
        rerun_policy: RerunPolicy | None = None,
    ) -> None:
        self._config = config or SandboxConfig()
        self._rerun = rerun_policy or RerunPolicy()
        self._launch = launcher or subprocess.Popen
        self._aux = aux_runner or subprocess.run
        self._which = which or (lambda name: shutil.which(name))
        self._probe = probe or subprocess.run
        self._junit = JUnitReportParser()

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def check_ready(self) -> str:
        """Verify the sandbox is usable; return the runtime path or raise.

        Checks the runtime binary, that its daemon answers, that the image is
        already present (images are never pulled) and that a custom seccomp
        profile exists. Any failure raises ``SandboxUnavailableError``.
        """

        runtime_path = self._which(self._config.runtime)
        if runtime_path is None:
            raise SandboxUnavailableError(
                f"container runtime '{self._config.runtime}' not found"
            )
        profile = self._config.seccomp_profile
        if profile and not Path(profile).is_file():
            raise SandboxUnavailableError("configured seccomp profile file not found")
        for label, argv in (
            ("container runtime daemon is not reachable", [runtime_path, "version"]),
            (
                f"sandbox image '{self._config.image}' is not present locally",
                [runtime_path, "image", "inspect", self._config.image],
            ),
        ):
            try:
                done = self._probe(  # noqa: S603 - argv list, no shell
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    env=_runtime_cli_env(),
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SandboxUnavailableError(
                    f"container runtime check failed ({exc.__class__.__name__})"
                ) from exc
            if getattr(done, "returncode", 1) != 0:
                raise SandboxUnavailableError(label)
        return runtime_path

    def run(self, plan: TestRunPlan, repository_path: Path) -> TestRunResult:
        """Execute all commands of ``plan`` against a snapshot of the checkout."""

        started = time.monotonic()
        outputs: list[str] = []
        try:
            runtime_path = self.check_ready()
        except SandboxUnavailableError as exc:
            error = _CommandOutcome(error=f"sandbox unavailable, refusing to execute: {exc}")
            return build_run_result(plan, [error], outputs, started)

        root = Path(tempfile.mkdtemp(prefix="radius-sandbox-"))
        try:
            workspace = root / "workspace"
            try:
                _snapshot_repository(repository_path, workspace)
            except OSError as exc:
                error = _CommandOutcome(
                    error=f"could not snapshot repository ({exc.__class__.__name__})"
                )
                return build_run_result(plan, [error], outputs, started)
            outcomes = [
                self._run_command(
                    runtime_path, command, args, workspace, root / f"cmd-{index}", outputs
                )
                for index, (command, args) in enumerate(plan.command_plan)
            ]
            return build_run_result(plan, outcomes, outputs, started)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _run_command(
        self,
        runtime_path: str,
        command: str,
        args: tuple[str, ...],
        workspace: Path,
        scratch: Path,
        outputs: list[str],
    ) -> _CommandOutcome:
        outcome, results_dir, is_pytest = self._run_once(
            runtime_path, command, args, workspace, scratch, outputs
        )
        if not (
            self._rerun.enabled and is_pytest and outcome.error is None and outcome.failed > 0
        ):
            return outcome
        return self._rerun_failures(
            runtime_path, command, args, workspace, scratch, outputs, outcome, results_dir
        )

    def _rerun_failures(
        self,
        runtime_path: str,
        command: str,
        args: tuple[str, ...],
        workspace: Path,
        scratch: Path,
        outputs: list[str],
        outcome: _CommandOutcome,
        first_results: Path,
    ) -> _CommandOutcome:
        """Rerun failed cases (F-11); reclassify those that pass as ``flaky``.

        Each rerun is a fresh hardened container with the same limits and
        timeout as the first run. A sandbox/runtime error (including exit codes
        137/152/153) aborts the reruns and leaves the original failures as
        failures: an error is never evidence of flakiness. Worst case wall time
        per command is ``(1 + reruns) * timeout_seconds``.
        """

        failed_cases = [
            case
            for case in _junit_cases(first_results / "junit.xml")
            if case.outcome == CaseOutcome.FAILED
        ]
        if not failed_cases or len(failed_cases) != outcome.failed:
            return outcome  # cannot identify the failures precisely: stay failed
        files = {case.key: resolve_case_file(case, workspace) for case in failed_cases}
        if all(files.values()):
            test_files = set(planned_test_files(args))
            rerun_args = tuple(a for a in args if a not in test_files) + tuple(
                sorted({f for f in files.values() if f})
            )
        else:
            rerun_args = args
        ids = {
            case.key: f"{files[case.key] or case.classname or ''}::{case.name or ''}"
            for case in failed_cases
        }
        recovered: set[tuple[str, str, str]] = set()
        attempts = 0
        for attempt in range(1, self._rerun.reruns + 1):
            rerun_outcome, rerun_dir, _ = self._run_once(
                runtime_path,
                command,
                rerun_args,
                workspace,
                scratch.parent / f"{scratch.name}-rerun-{attempt}",
                outputs,
            )
            if rerun_outcome.error is not None:
                outputs.append(f"Radius rerun {attempt} aborted: {rerun_outcome.error}")
                break
            attempts += 1
            for case in _junit_cases(rerun_dir / "junit.xml"):
                if case.key in ids and case.outcome == CaseOutcome.PASSED:
                    recovered.add(case.key)
            if recovered == set(ids):
                break
        outputs.append(
            f"Radius rerun policy: {len(ids)} failing test(s), {attempts} rerun(s) "
            f"completed, {len(recovered)} flaky, {len(ids) - len(recovered)} stable_fail."
        )
        outcome.failed -= len(recovered)
        outcome.flaky += len(recovered)
        outcome.flaky_tests = tuple(sorted(ids[key] for key in recovered))
        return outcome

    def _run_once(
        self,
        runtime_path: str,
        command: str,
        args: tuple[str, ...],
        workspace: Path,
        scratch: Path,
        outputs: list[str],
    ) -> tuple[_CommandOutcome, Path, bool]:
        results_dir = scratch / "results"
        results_dir.mkdir(parents=True)
        # The container runs as nobody; it must be able to write its report here.
        results_dir.chmod(0o777)
        inner_argv, is_pytest = sandbox_command(command, args)
        container_name = f"radius-sbx-{uuid4().hex[:16]}"
        argv = build_container_argv(
            self._config,
            runtime_path=runtime_path,
            container_name=container_name,
            workspace_dir=workspace,
            results_dir=results_dir,
            command=inner_argv,
        )
        execution = self._execute(argv, runtime_path, container_name, scratch)
        for stream in (execution.stdout, execution.stderr):
            if stream:
                outputs.append(stream)
        if execution.failure is not None:
            error = f"{command}: {execution.failure}"
            return _CommandOutcome(error=error), results_dir, is_pytest
        for table in (RUNTIME_EXIT_CODES, CONTAINED_EXIT_CODES):
            if execution.returncode in table:
                error = f"{command}: {table[execution.returncode]}"
                return _CommandOutcome(error=error), results_dir, is_pytest
        if is_pytest:
            outcome = pytest_outcome(
                self._junit, execution.returncode, results_dir / "junit.xml"
            )
        else:
            outcome = exit_code_outcome(
                command,
                execution.returncode,
                execution.stdout + execution.stderr,
                planned_test_files(args),
            )
        return outcome, results_dir, is_pytest

    def _execute(
        self,
        argv: list[str],
        runtime_path: str,
        container_name: str,
        scratch: Path,
    ) -> _Execution:
        out_path = scratch / "stdout.txt"
        err_path = scratch / "stderr.txt"
        result = _Execution()
        process: _Process | None = None
        stop = threading.Event()
        overflow = threading.Event()
        watchdog: threading.Thread | None = None
        try:
            with out_path.open("w+b") as out_f, err_path.open("w+b") as err_f:
                try:
                    process = self._launch(  # noqa: S603 - argv list, no shell
                        argv,
                        stdout=out_f,
                        stderr=err_f,
                        stdin=subprocess.DEVNULL,
                        # The runtime CLI only needs to find its daemon socket;
                        # it never receives worker secrets.
                        env=_runtime_cli_env(),
                    )
                except FileNotFoundError:
                    result.failure = (
                        f"container runtime '{self._config.runtime}' not found"
                    )
                    return result
                except OSError as exc:
                    result.failure = (
                        f"could not start container runtime ({exc.__class__.__name__})"
                    )
                    return result
                watchdog = threading.Thread(
                    target=self._watch_output,
                    args=(stop, overflow, (out_path, err_path), runtime_path, container_name),
                    daemon=True,
                )
                watchdog.start()
                try:
                    result.returncode = process.wait(
                        timeout=self._config.timeout_seconds
                    )
                except subprocess.TimeoutExpired:
                    result.failure = (
                        f"timed out after {self._config.timeout_seconds} seconds"
                    )
                    self._kill_container(runtime_path, container_name)
                    record_sandbox_kill("timeout")
                    process.kill()
                    _wait_quietly(process)
        finally:
            stop.set()
            if watchdog is not None:
                watchdog.join(timeout=5)
            if overflow.is_set() and result.failure is None:
                result.failure = (
                    f"output exceeded {self._config.max_output_bytes} bytes; container killed"
                )
            if result.failure is not None and process is not None:
                # --rm covers normal exits; make sure nothing is left behind.
                self._remove_container(runtime_path, container_name)
        result.stdout = _read_capped(out_path, self.MAX_OUTPUT_SIZE)
        result.stderr = _read_capped(err_path, self.MAX_OUTPUT_SIZE)
        return result

    def _watch_output(
        self,
        stop: threading.Event,
        overflow: threading.Event,
        paths: tuple[Path, Path],
        runtime_path: str,
        container_name: str,
    ) -> None:
        """Kill the container if its captured output outgrows the host-side cap."""

        limit = self._config.max_output_bytes
        while not stop.wait(_WATCHDOG_INTERVAL_SECONDS):
            try:
                oversized = any(path.stat().st_size > limit for path in paths)
            except OSError:
                continue
            if oversized:
                overflow.set()
                self._kill_container(runtime_path, container_name)
                return

    def _kill_container(self, runtime_path: str, container_name: str) -> None:
        self._aux_call([runtime_path, "kill", container_name])

    def _remove_container(self, runtime_path: str, container_name: str) -> None:
        self._aux_call([runtime_path, "rm", "-f", container_name])

    def _aux_call(self, argv: list[str]) -> None:
        try:
            self._aux(  # noqa: S603 - argv list, no shell
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=_runtime_cli_env(),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            LOGGER.warning(
                "sandbox container cleanup failed",
                extra={"argv": argv[1:], "error": exc.__class__.__name__},
            )


def _junit_cases(path: Path) -> tuple:
    """Parse the cases of a JUnit report written by the sandbox, or ``()``."""

    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 20 * 1024 * 1024:
            return ()
        return report_cases(path.read_bytes())
    except Exception:  # noqa: BLE001 - an unreadable report means "no evidence"
        return ()


def resolve_case_file(case, workspace: Path) -> str | None:
    """Map a JUnit case to a repo-relative ``.py`` file in the snapshot, if any."""

    candidates: list[str] = []
    if case.file:
        candidates.append(case.file.replace("\\", "/"))
    parts = [p for p in (case.classname or "").split(".") if p]
    for end in range(len(parts), 0, -1):
        candidates.append("/".join(parts[:end]) + ".py")
    for candidate in candidates:
        if candidate.startswith(("-", "/")) or ".." in candidate.split("/"):
            continue
        if (workspace / candidate).is_file():
            return candidate
    return None


def _runtime_cli_env() -> dict[str, str]:
    """Minimal env for the docker/podman CLI process itself (not the container)."""

    allowed = {"PATH", "DOCKER_HOST", "CONTAINER_HOST", "XDG_RUNTIME_DIR", "HOME"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _snapshot_repository(source: Path, destination: Path) -> None:
    """Copy the checkout so the sandbox never touches the shared repository cache."""

    shutil.copytree(
        source,
        destination,
        symlinks=True,  # copy links as links; never follow them out of the repo
        ignore=shutil.ignore_patterns(".git"),
    )
    # Make the snapshot readable (not writable) by the unprivileged container user.
    for dirpath, dirnames, filenames in os.walk(destination):
        for name in (*dirnames, "."):
            path = Path(dirpath) / name
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IROTH | stat.S_IXOTH)
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IROTH)


def _read_capped(path: Path, limit: int) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _wait_quietly(process: _Process) -> None:
    try:
        process.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass
