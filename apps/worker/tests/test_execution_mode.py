"""Test execution mode selection and its fail-closed production guard."""

from __future__ import annotations

import logging

import pytest
import radius_worker.runner as worker_runner
from radius_shared.errors import ValidationError
from radius_testing.infrastructure import (
    ContainerSandboxRunner,
    DisabledTestRunner,
    SubprocessTestRunner,
)
from radius_worker.config import WorkerSettings
from radius_worker.execution_mode import (
    TestExecutionMode,
    UnsafeExecutionRefusedError,
    build_test_runner,
    resolve_test_execution_mode,
)

_ENV_KEYS = (
    "RADIUS_ENV",
    "WORKER_EXECUTE_TESTS",
    "WORKER_TEST_EXECUTION_MODE",
    "RADIUS_ALLOW_UNSAFE_EXECUTION",
    "WORKER_SANDBOX_IMAGE",
    "WORKER_SANDBOX_RUNTIME",
    "WORKER_SANDBOX_MEMORY",
    "WORKER_SANDBOX_CPUS",
    "WORKER_SANDBOX_PIDS_LIMIT",
    "WORKER_TEST_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _settings(**env: str) -> WorkerSettings:
    return WorkerSettings(_env_file=None, **env)


def test_default_configuration_never_executes_repository_code() -> None:
    settings = _settings()

    mode = resolve_test_execution_mode(settings)
    assert mode == TestExecutionMode.DISABLED
    assert isinstance(build_test_runner(mode, settings), DisabledTestRunner)
    assert resolve_test_execution_mode(None) == TestExecutionMode.DISABLED


def test_default_sql_orchestrator_has_execution_gate_closed() -> None:
    for settings in (None, _settings()):
        orchestrator = worker_runner._create_sql_orchestrator(session=None, settings=settings)
        assert orchestrator._execute_tests is False
        assert isinstance(orchestrator._testing._runner, DisabledTestRunner)


def test_legacy_flag_maps_to_unsafe_with_loud_warning(caplog) -> None:
    settings = _settings(WORKER_EXECUTE_TESTS="true")

    with caplog.at_level(logging.WARNING):
        mode = resolve_test_execution_mode(settings)

    assert mode == TestExecutionMode.UNSAFE_IN_PROCESS
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "DEPRECATED" in messages
    assert "SECURITY WARNING" in messages
    assert isinstance(build_test_runner(mode, settings), SubprocessTestRunner)


def test_explicit_mode_overrides_legacy_flag() -> None:
    settings = _settings(WORKER_EXECUTE_TESTS="true", WORKER_TEST_EXECUTION_MODE="disabled")
    assert resolve_test_execution_mode(settings) == TestExecutionMode.DISABLED


@pytest.mark.parametrize("environment", ["production", "uat"])
@pytest.mark.parametrize(
    "env",
    [{"WORKER_TEST_EXECUTION_MODE": "unsafe_in_process"}, {"WORKER_EXECUTE_TESTS": "true"}],
)
def test_unsafe_mode_is_refused_in_protected_environments(environment, env) -> None:
    settings = _settings(RADIUS_ENV=environment, **env)

    with pytest.raises(UnsafeExecutionRefusedError):
        resolve_test_execution_mode(settings)
    with pytest.raises(UnsafeExecutionRefusedError):
        worker_runner._create_sql_orchestrator(session=None, settings=settings)


def test_worker_refuses_to_start_with_unsafe_mode_in_production(monkeypatch) -> None:
    engine_created = []
    monkeypatch.setattr(
        worker_runner, "create_database_engine", lambda s: engine_created.append(s)
    )
    settings = _settings(RADIUS_ENV="production", WORKER_TEST_EXECUTION_MODE="unsafe_in_process")

    with pytest.raises(UnsafeExecutionRefusedError):
        worker_runner.create_sql_worker_runtime(settings)
    assert engine_created == []


def test_unsafe_mode_allowed_in_production_only_with_explicit_override(caplog) -> None:
    settings = _settings(
        RADIUS_ENV="production",
        WORKER_TEST_EXECUTION_MODE="unsafe_in_process",
        RADIUS_ALLOW_UNSAFE_EXECUTION="true",
    )

    with caplog.at_level(logging.WARNING):
        assert resolve_test_execution_mode(settings) == TestExecutionMode.UNSAFE_IN_PROCESS
    assert "SECURITY WARNING" in caplog.text


def test_unsafe_mode_allowed_in_development_with_warning(caplog) -> None:
    settings = _settings(RADIUS_ENV="development", WORKER_TEST_EXECUTION_MODE="unsafe_in_process")
    with caplog.at_level(logging.WARNING):
        assert resolve_test_execution_mode(settings) == TestExecutionMode.UNSAFE_IN_PROCESS
    assert "SECURITY WARNING" in caplog.text


def test_sandbox_mode_builds_configured_container_runner() -> None:
    settings = _settings(
        RADIUS_ENV="production",
        WORKER_TEST_EXECUTION_MODE="sandbox",
        WORKER_SANDBOX_IMAGE="registry.example/radius-sandbox:1",
        WORKER_SANDBOX_RUNTIME="podman",
        WORKER_SANDBOX_MEMORY="512m",
        WORKER_SANDBOX_CPUS="0.5",
        WORKER_SANDBOX_PIDS_LIMIT="64",
        WORKER_TEST_TIMEOUT_SECONDS="90",
    )

    mode = resolve_test_execution_mode(settings)
    runner = build_test_runner(mode, settings)

    assert mode == TestExecutionMode.SANDBOX
    assert isinstance(runner, ContainerSandboxRunner)
    config = runner.config
    assert (config.image, config.runtime, config.memory, config.cpus) == (
        "registry.example/radius-sandbox:1",
        "podman",
        "512m",
        "0.5",
    )
    assert (config.pids_limit, config.timeout_seconds) == (64, 90)
    orchestrator = worker_runner._create_sql_orchestrator(session=None, settings=settings)
    assert orchestrator._execute_tests is True
    assert isinstance(orchestrator._testing._runner, ContainerSandboxRunner)


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        resolve_test_execution_mode(_settings(WORKER_TEST_EXECUTION_MODE="yolo"))


def test_disabled_runner_never_reports_pass(tmp_path) -> None:
    from uuid import uuid4

    from radius_testing.domain import TestRunPlan, TestRunStatus

    plan = TestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=(),
        command_plan=(("python", ("-c", "open('pwned','w')")),),
    )
    result = DisabledTestRunner().run(plan, tmp_path)

    assert result.status == TestRunStatus.ERROR
    assert result.passed == 0
    assert not (tmp_path / "pwned").exists()
