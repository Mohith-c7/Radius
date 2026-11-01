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

    def save_test_cases(
        self,
        tests: tuple[TestCase, ...],
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Persist discovered test cases for one repository."""

    def list_test_cases(
        self,
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Return known test cases, scoped to one repository when given."""

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
