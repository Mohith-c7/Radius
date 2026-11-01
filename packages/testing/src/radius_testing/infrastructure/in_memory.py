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
        self._tests: dict[tuple[UUID | None, str], TestCase] = {}
        self._selections: dict[UUID, TestSelection] = {}
        self._plans: dict[UUID, TestRunPlan] = {}
        self._results: dict[UUID, TestRunResult] = {}

    def save_test_cases(
        self,
        tests: tuple[TestCase, ...],
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Persist discovered test cases by (repository, path)."""

        for test in tests:
            self._tests[(repository_id, test.path.value)] = test
        return self.list_test_cases(repository_id)

    def list_test_cases(
        self,
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Return known test cases, scoped to one repository when given."""

        keys = sorted(
            (key for key in self._tests if repository_id is None or key[0] == repository_id),
            key=lambda key: (key[1], str(key[0])),
        )
        return tuple(self._tests[key] for key in keys)

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
