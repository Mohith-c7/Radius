"""Subprocess-backed test runner.

SECURITY: this runner executes code from the repository under analysis. That
code is untrusted (any pull request author controls it). It strips secrets
from the child environment, but it does NOT sandbox the process: the child
shares the worker's user, filesystem, and network -- and, running as the same
uid, it can read the worker's full environment via ``/proc/<ppid>/environ``.
Only enable it in an isolated, credential-free execution environment. Prefer
``ContainerSandboxRunner`` (``WORKER_TEST_EXECUTION_MODE=sandbox``); see
``docs/security/EXECUTION_ISOLATION.md``.

Result semantics are deliberately conservative:

* Real per-test counts are taken from JUnit XML when the framework emits it
  (pytest). Otherwise counts are file-level and marked as such in the output.
* A missing runner binary, a timeout, an interrupted session, or a usage /
  internal error yields ``TestRunStatus.ERROR`` -- never ``PASSED`` and never a
  fabricated failure count.
* pytest exit code 5 ("no tests collected") contributes zero tests rather
  than being reported as a pass or a failure.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from radius_testing.domain.entities import TestRunPlan, TestRunResult
from radius_testing.domain.enums import TestRunStatus
from radius_testing.infrastructure.junit_parser import JUnitReportParser

PYTEST_EXIT_TESTS_FAILED = 1
PYTEST_EXIT_NO_TESTS_COLLECTED = 5
NPX_MISSING_MARKERS = (
    "could not determine executable to run",
    "command not found",
    "npm ERR! could not determine executable",
    "npx canceled due to missing packages",
)


@dataclass(slots=True)
class _CommandOutcome:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: str | None = None


class SubprocessTestRunner:
    """Execute planned test commands with timeout and output capture."""

    SAFE_ENV_VARS = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "LANG",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PYTHONPATH",
        "HOME",
    }
    MAX_OUTPUT_SIZE = 500 * 1024  # 500KB

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout_seconds = timeout_seconds
        self._junit = JUnitReportParser()

    def _get_sanitized_env(self) -> dict[str, str]:
        """Strip sensitive secrets from the environment."""

        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in self.SAFE_ENV_VARS
        }

    def run(self, plan: TestRunPlan, repository_path: Path) -> TestRunResult:
        """Execute all commands in a test run plan."""

        started = time.monotonic()
        outputs: list[str] = []
        env = self._get_sanitized_env()

        outcomes = [
            self._run_command(command, args, repository_path, env, outputs)
            for command, args in plan.command_plan
        ]
        return build_run_result(plan, outcomes, outputs, started)

    def _run_command(
        self,
        command: str,
        args: tuple[str, ...],
        repository_path: Path,
        env: dict[str, str],
        outputs: list[str],
    ) -> _CommandOutcome:
        is_pytest = command == "python" and args[:2] == ("-m", "pytest")
        test_files = planned_test_files(args)
        with tempfile.TemporaryDirectory(prefix="radius-run-") as scratch:
            junit_path = Path(scratch) / "junit.xml"
            argv = [command, *args]
            if is_pytest:
                argv = [
                    command,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={junit_path}",
                    *args[2:],
                ]
            stdout, stderr, returncode, failure = self._execute(
                argv, repository_path, env, Path(scratch)
            )
            for stream in (stdout, stderr):
                if stream:
                    outputs.append(stream)
            if failure is not None:
                return _CommandOutcome(error=f"{command}: {failure}")

            if is_pytest:
                return self._pytest_outcome(returncode, junit_path)
            return self._exit_code_outcome(command, returncode, stdout + stderr, test_files)

    def _execute(
        self,
        argv: list[str],
        repository_path: Path,
        env: dict[str, str],
        scratch: Path,
    ) -> tuple[str, str, int, str | None]:
        out_path = scratch / "stdout.txt"
        err_path = scratch / "stderr.txt"
        try:
            with out_path.open("w+", encoding="utf-8", errors="replace") as out_f, err_path.open(
                "w+", encoding="utf-8", errors="replace"
            ) as err_f:
                completed = subprocess.run(  # noqa: S603 - argv list, no shell
                    argv,
                    cwd=repository_path,
                    stdout=out_f,
                    stderr=err_f,
                    stdin=subprocess.DEVNULL,
                    timeout=self._timeout_seconds,
                    env=env,
                    check=False,
                )
                returncode = completed.returncode
                failure = None
        except FileNotFoundError:
            return "", "", -1, "test runner executable not found"
        except subprocess.TimeoutExpired:
            returncode = -1
            failure = f"timed out after {self._timeout_seconds} seconds"
        except OSError as exc:
            return "", "", -1, f"could not start test runner ({exc.__class__.__name__})"
        stdout = out_path.read_text(encoding="utf-8", errors="replace")[: self.MAX_OUTPUT_SIZE]
        stderr = err_path.read_text(encoding="utf-8", errors="replace")[: self.MAX_OUTPUT_SIZE]
        return stdout, stderr, returncode, failure

    def _pytest_outcome(self, returncode: int, junit_path: Path) -> _CommandOutcome:
        return pytest_outcome(self._junit, returncode, junit_path)

    @staticmethod
    def _exit_code_outcome(
        command: str,
        returncode: int,
        combined_output: str,
        test_files: list[str],
    ) -> _CommandOutcome:
        return exit_code_outcome(command, returncode, combined_output, test_files)


# --- Result interpretation shared by every runner (in-process and sandboxed) ---

MAX_JUNIT_REPORT_BYTES = 20 * 1024 * 1024


def pytest_outcome(
    junit: JUnitReportParser,
    returncode: int,
    junit_path: Path,
) -> _CommandOutcome:
    """Interpret a pytest exit code plus its JUnit report conservatively."""

    if returncode == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return _CommandOutcome()
    if returncode not in (0, PYTEST_EXIT_TESTS_FAILED):
        return _CommandOutcome(
            error=f"pytest exited with code {returncode} (interrupted, internal, or usage error)"
        )
    if not junit_path.is_file() or junit_path.is_symlink():
        return _CommandOutcome(error="pytest did not produce a JUnit report")
    if junit_path.stat().st_size > MAX_JUNIT_REPORT_BYTES:
        return _CommandOutcome(error="pytest JUnit report exceeds the size limit")
    parsed = junit.parse(junit_path.read_bytes(), uuid4())
    outcome = _CommandOutcome(
        total=parsed.total_tests,
        passed=parsed.passed,
        failed=parsed.failed,
        skipped=parsed.skipped,
    )
    if returncode == PYTEST_EXIT_TESTS_FAILED and outcome.failed == 0:
        # Exit code says failure but the report shows none: do not guess.
        outcome.error = "pytest reported failure but JUnit report shows no failed tests"
    return outcome


def exit_code_outcome(
    command: str,
    returncode: int,
    combined_output: str,
    test_files: list[str],
) -> _CommandOutcome:
    """Interpret a framework that only reports a process exit code."""

    lowered = combined_output.lower()
    if returncode != 0 and any(marker.lower() in lowered for marker in NPX_MISSING_MARKERS):
        return _CommandOutcome(error=f"{command} is not installed in the repository")
    count = len(test_files)
    if returncode == 0:
        # File-level granularity only: the framework did not emit per-test data.
        return _CommandOutcome(total=count, passed=count)
    return _CommandOutcome(total=count, failed=count)


def planned_test_files(args: tuple[str, ...]) -> list[str]:
    """Return the positional test-file arguments of a planned command."""

    return [
        arg
        for arg in args
        if not arg.startswith("-") and arg not in {"jest", "vitest", "run", "pytest"}
    ]


def build_run_result(
    plan: TestRunPlan,
    outcomes: list[_CommandOutcome],
    outputs: list[str],
    started: float,
) -> TestRunResult:
    """Aggregate per-command outcomes. Any error makes the run ``ERROR``."""

    totals = _CommandOutcome()
    errors: list[str] = []
    for outcome in outcomes:
        totals.total += outcome.total
        totals.passed += outcome.passed
        totals.failed += outcome.failed
        totals.skipped += outcome.skipped
        if outcome.error:
            errors.append(outcome.error)

    if errors:
        status = TestRunStatus.ERROR
        outputs.insert(0, "Radius test execution incomplete: " + "; ".join(errors))
    elif totals.failed:
        status = TestRunStatus.FAILED
    else:
        status = TestRunStatus.PASSED

    return TestRunResult(
        id=uuid4(),
        analysis_id=plan.analysis_id,
        status=status,
        total_tests=totals.total,
        passed=totals.passed,
        failed=totals.failed,
        skipped=totals.skipped,
        duration_ms=int((time.monotonic() - started) * 1000),
        output="\n".join(item for item in outputs if item),
    )
