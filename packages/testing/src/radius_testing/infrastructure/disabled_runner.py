"""Runner used when test execution is disabled (the default)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from radius_testing.domain.entities import TestRunPlan, TestRunResult
from radius_testing.domain.enums import TestRunStatus


class DisabledTestRunner:
    """Never executes anything; any call yields an ``ERROR`` (never ``PASSED``).

    Wired when ``WORKER_TEST_EXECUTION_MODE=disabled`` so that even a code path
    that bypasses the orchestrator's execution gate cannot run repository code.
    """

    def run(self, plan: TestRunPlan, repository_path: Path) -> TestRunResult:
        return TestRunResult(
            id=uuid4(),
            analysis_id=plan.analysis_id,
            status=TestRunStatus.ERROR,
            total_tests=0,
            passed=0,
            failed=0,
            skipped=0,
            duration_ms=0,
            output="Radius test execution incomplete: test execution is disabled",
        )
