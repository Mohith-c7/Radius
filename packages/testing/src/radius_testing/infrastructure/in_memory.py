"""In-memory testing infrastructure."""

from uuid import UUID

from radius_testing.domain.entities import (
    TestCase,
    TestRunPlan,
    TestRunResult,
    TestSelection,
)


class InMemoryTestStore:
    """Store testing state in memory."""

    def __init__(self) -> None:
        self._tests: dict[str, TestCase] = {}
        self._selections: dict[UUID, TestSelection] = {}
        self._plans: dict[UUID, TestRunPlan] = {}
        self._results: dict[UUID, TestRunResult] = {}

    def save_test_cases(self, tests: tuple[TestCase, ...]) -> tuple[TestCase, ...]:
        """Persist discovered test cases."""

        for test in tests:
            self._tests[test.path.value] = test
        return self.list_test_cases()

    def list_test_cases(self) -> tuple[TestCase, ...]:
        """Return known test cases."""

        return tuple(self._tests[path] for path in sorted(self._tests))

    def save_selection(self, selection: TestSelection) -> TestSelection:
        """Persist a test selection."""

        self._selections[selection.analysis_id] = selection
        return selection

    def get_selection(self, analysis_id: UUID) -> TestSelection | None:
        """Return selection for an analysis."""

        return self._selections.get(analysis_id)

    def save_run_plan(self, plan: TestRunPlan) -> TestRunPlan:
        """Persist a structured run plan."""

        self._plans[plan.analysis_id] = plan
        return plan

    def get_run_plan(self, analysis_id: UUID) -> TestRunPlan | None:
        """Return test run plan for an analysis."""

        return self._plans.get(analysis_id)

    def save_run_result(self, result: TestRunResult) -> TestRunResult:
        """Persist executed test run result."""

        self._results[result.analysis_id] = result
        return result

    def get_run_result(self, analysis_id: UUID) -> TestRunResult | None:
        """Return executed test run result."""

        return self._results.get(analysis_id)
