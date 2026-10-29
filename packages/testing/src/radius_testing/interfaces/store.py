"""Testing persistence interfaces."""

from typing import Protocol
from uuid import UUID

from radius_testing.domain.entities import (
    TestCase,
    TestRunPlan,
    TestRunResult,
    TestSelection,
)


class TestStore(Protocol):
    """Persistence contract for test discovery and selection state."""

    def save_test_cases(self, tests: tuple[TestCase, ...]) -> tuple[TestCase, ...]:
        """Persist discovered test cases."""

    def list_test_cases(self) -> tuple[TestCase, ...]:
        """Return known test cases."""

    def save_selection(self, selection: TestSelection) -> TestSelection:
        """Persist a test selection."""

    def get_selection(self, analysis_id: UUID) -> TestSelection | None:
        """Return selection for an analysis."""

    def save_run_plan(self, plan: TestRunPlan) -> TestRunPlan:
        """Persist a structured run plan."""

    def get_run_plan(self, analysis_id: UUID) -> TestRunPlan | None:
        """Return test run plan for an analysis."""

    def save_run_result(self, result: TestRunResult) -> TestRunResult:
        """Persist test execution result."""

    def get_run_result(self, analysis_id: UUID) -> TestRunResult | None:
        """Return test execution result."""

    def get_test_history(self, analysis_id: UUID) -> list[dict]:
        """Return test execution history for an analysis."""

    def get_test_statistics(self, analysis_id: UUID) -> dict:
        """Return test execution statistics for an analysis."""

    def get_recent_executions(
        self, repository_id: UUID | None = None, limit: int = 50
    ) -> list[dict]:
        """Return recent test executions across analyses."""
