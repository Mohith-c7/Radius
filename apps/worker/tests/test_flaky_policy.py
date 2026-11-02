"""F-11: rerun / flaky-policy configuration and its threading into test evidence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from radius_testing.domain import RerunPolicy
from radius_testing.infrastructure import ContainerSandboxRunner
from radius_worker.config import WorkerSettings
from radius_worker.execution_mode import TestExecutionMode, build_test_runner
from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("WORKER_TEST_RERUNS", "WORKER_FLAKY_POLICY"):
        monkeypatch.delenv(key, raising=False)


def _settings(**env: str) -> WorkerSettings:
    return WorkerSettings(_env_file=None, **env)


def test_defaults_are_off_and_exclude() -> None:
    settings = _settings()
    assert settings.test_reruns == 0
    assert settings.flaky_policy == "exclude"
    runner = build_test_runner(TestExecutionMode.SANDBOX, settings)
    assert isinstance(runner, ContainerSandboxRunner)
    assert runner._rerun == RerunPolicy(reruns=0)


def test_reruns_configure_the_sandbox_runner_and_are_bounded() -> None:
    runner = build_test_runner(TestExecutionMode.SANDBOX, _settings(WORKER_TEST_RERUNS="2"))
    assert runner._rerun.reruns == 2
    with pytest.raises(ValueError):
        _settings(WORKER_TEST_RERUNS="11")
    with pytest.raises(ValueError):
        _settings(WORKER_FLAKY_POLICY="ignore")


class _Testing:
    def __init__(self, **result) -> None:
        base = {
            "status": "passed",
            "total_tests": 3,
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "coverage_percent": None,
            "output": "",
            "flaky": 1,
            "flaky_tests": ("tests/test_a.py::t",),
        }
        self._result = SimpleNamespace(**{**base, **result})

    def execute_test_run(self, command):
        return self._result


def _evidence(policy: str):
    orchestrator = Phase1AnalysisOrchestrator(
        None, None, None, None, _Testing(), None, flaky_policy=policy  # type: ignore[arg-type]
    )
    command = ExecuteAnalysisCommand(
        analysis_id=uuid4(), repository_id=uuid4(), repository_path=Path(".")
    )
    return orchestrator._run_or_defer_tests(command, 1)


def test_exclude_policy_keeps_flaky_out_of_passed_and_failed() -> None:
    evidence = _evidence("exclude")
    assert (evidence.passed, evidence.failed, evidence.flaky) == (2, 0, 1)
    assert evidence.flaky_tests == ("tests/test_a.py::t",)


def test_fail_policy_counts_flaky_as_failures_never_passes() -> None:
    evidence = _evidence("fail")
    assert (evidence.passed, evidence.failed, evidence.flaky) == (2, 1, 0)
