"""Selection of how (and whether) the worker executes pull-request tests.

The worker holds ``DATABASE_URL`` and the GitHub App private key, and the tests
are code controlled by the pull-request author. Modes:

* ``disabled`` (default): nothing is executed; tests run in the customer's CI
  and results are ingested.
* ``sandbox``: each command runs in an ephemeral, network-less, read-only,
  unprivileged container (``ContainerSandboxRunner``).
* ``unsafe_in_process``: legacy ``SubprocessTestRunner``. The child shares the
  worker's uid, network and filesystem and can read the worker's environment
  through ``/proc/<ppid>/environ``. Refused in uat/production unless
  ``RADIUS_ALLOW_UNSAFE_EXECUTION=true``.
"""

from __future__ import annotations

from enum import StrEnum

from radius_shared.config import RuntimeEnvironment
from radius_shared.errors import ValidationError
from radius_shared.logging import get_logger
from radius_testing.infrastructure import (
    ContainerSandboxRunner,
    DisabledTestRunner,
    SandboxConfig,
    SubprocessTestRunner,
)
from radius_testing.interfaces.runner import TestRunner

from radius_worker.config import WorkerSettings

LOGGER = get_logger(__name__)

_PROTECTED_ENVIRONMENTS = frozenset({RuntimeEnvironment.UAT, RuntimeEnvironment.PRODUCTION})


class TestExecutionMode(StrEnum):
    """Supported test execution modes."""

    __test__ = False  # not a pytest test class

    DISABLED = "disabled"
    SANDBOX = "sandbox"
    UNSAFE_IN_PROCESS = "unsafe_in_process"


class UnsafeExecutionRefusedError(ValidationError):
    """Raised when unsafe in-process execution is configured where it is forbidden."""

    code = "UNSAFE_EXECUTION_REFUSED"


def resolve_test_execution_mode(settings: WorkerSettings | None) -> TestExecutionMode:
    """Resolve the effective mode, failing closed on unsafe production config."""

    if settings is None:
        return TestExecutionMode.DISABLED

    raw = (settings.test_execution_mode or "").strip().lower()
    if raw:
        try:
            mode = TestExecutionMode(raw)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in TestExecutionMode)
            msg = f"WORKER_TEST_EXECUTION_MODE={raw!r} is invalid; use one of: {allowed}."
            raise ValidationError(msg) from exc
        if settings.execute_tests and mode != TestExecutionMode.UNSAFE_IN_PROCESS:
            LOGGER.warning(
                "WORKER_EXECUTE_TESTS is ignored because WORKER_TEST_EXECUTION_MODE is set.",
                extra={"test_execution_mode": mode.value},
            )
    elif settings.execute_tests:
        LOGGER.warning(
            "DEPRECATED: WORKER_EXECUTE_TESTS=true maps to "
            "WORKER_TEST_EXECUTION_MODE=unsafe_in_process. Set "
            "WORKER_TEST_EXECUTION_MODE explicitly (prefer 'sandbox')."
        )
        mode = TestExecutionMode.UNSAFE_IN_PROCESS
    else:
        mode = TestExecutionMode.DISABLED

    if mode == TestExecutionMode.UNSAFE_IN_PROCESS:
        if settings.environment in _PROTECTED_ENVIRONMENTS and not settings.allow_unsafe_execution:
            msg = (
                "Refusing unsafe_in_process test execution in "
                f"RADIUS_ENV={settings.environment.value}: pull-request code would run "
                "with access to the worker's database and GitHub App credentials. "
                "Use WORKER_TEST_EXECUTION_MODE=sandbox, or set "
                "RADIUS_ALLOW_UNSAFE_EXECUTION=true only if the worker itself is an "
                "isolated, credential-free sandbox."
            )
            raise UnsafeExecutionRefusedError(msg)
        LOGGER.warning(
            "SECURITY WARNING: unsafe_in_process test execution is enabled. "
            "Pull-request code runs as the worker user, with network access, and can "
            "read the worker's environment (DATABASE_URL, GITHUB_APP_PRIVATE_KEY) via "
            "/proc. See docs/security/EXECUTION_ISOLATION.md.",
            extra={"environment": settings.environment.value},
        )
    return mode


def build_test_runner(
    mode: TestExecutionMode,
    settings: WorkerSettings | None,
) -> TestRunner:
    """Return the runner for ``mode``. ``disabled`` never executes anything."""

    timeout = settings.test_timeout_seconds if settings is not None else 600
    if mode == TestExecutionMode.SANDBOX:
        if settings is None:
            return ContainerSandboxRunner(SandboxConfig(timeout_seconds=timeout))
        return ContainerSandboxRunner(
            SandboxConfig(
                image=settings.sandbox_image,
                runtime=settings.sandbox_runtime,
                memory=settings.sandbox_memory,
                cpus=settings.sandbox_cpus,
                pids_limit=settings.sandbox_pids_limit,
                tmpfs_size=settings.sandbox_tmpfs_size,
                timeout_seconds=timeout,
            )
        )
    if mode == TestExecutionMode.UNSAFE_IN_PROCESS:
        return SubprocessTestRunner(timeout_seconds=timeout)
    return DisabledTestRunner()
