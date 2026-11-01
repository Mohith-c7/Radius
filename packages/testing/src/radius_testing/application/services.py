from uuid import UUID

from radius_shared.errors import NotFoundError, ValidationError

from radius_testing.dto.commands import (
    DiscoverTestsCommand,
    ExecuteTestRunCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)
from radius_testing.dto.responses import (
    TestCaseResponse,
    TestDiscoveryResponse,
    TestRunPlanResponse,
    TestRunResultResponse,
    TestSelectionResponse,
)
from radius_testing.infrastructure.junit_parser import JUnitReportParser
from radius_testing.interfaces.discovery import TestDiscoverer
from radius_testing.interfaces.runner import TestCommandPlanner, TestRunner
from radius_testing.interfaces.selection import TestSelector
from radius_testing.interfaces.store import TestStore


class TestingApplicationService:
    """Coordinates deterministic test discovery, selection, and planning."""

    def __init__(
        self,
        discoverer: TestDiscoverer,
        selector: TestSelector,
        store: TestStore,
        planner: TestCommandPlanner,
        runner: TestRunner | None = None,
        parser: JUnitReportParser | None = None,
    ) -> None:
        self._discoverer = discoverer
        self._selector = selector
        self._store = store
        self._planner = planner
        self._runner = runner
        self._parser = parser or JUnitReportParser()


    def discover_tests(
        self,
        command: DiscoverTestsCommand,
    ) -> TestDiscoveryResponse:
        """Discover and store test cases."""

        tests = self.discover_test_cases(command)
        return TestDiscoveryResponse(
            test_count=len(tests),
            tests=tuple(TestCaseResponse.from_entity(test) for test in tests),
        )

    def discover_test_cases(self, command: DiscoverTestsCommand) -> tuple:
        """Discover, persist, and return the test cases of one snapshot."""

        if not command.repository_path.exists() or not command.repository_path.is_dir():
            msg = f"Repository path does not exist: {command.repository_path}."
            raise ValidationError(msg)
        discovered = self._discoverer.discover(command.repository_path)
        self._store.save_test_cases(discovered)
        return discovered

    def select_tests(self, command: SelectTestsCommand) -> TestSelectionResponse:
        """Select tests for changed and affected paths."""

        tests = (
            command.available_tests
            if command.available_tests is not None
            else self._store.list_test_cases()
        )
        selection = self._selector.select(
            command.analysis_id,
            tests,
            command.changed_file_paths,
            command.affected_file_paths,
            full_suite_reasons=command.full_suite_reasons,
        )
        return TestSelectionResponse.from_entity(
            self._store.save_selection(selection)
        )

    def plan_test_run(self, command: PlanTestRunCommand) -> TestRunPlanResponse:
        """Create a structured run plan from a saved selection."""

        selection = self._store.get_selection(command.analysis_id)
        if selection is None:
            msg = f"Test selection for analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)
        plan = self._planner.plan(
            command.analysis_id,
            tuple(selected.test_case for selected in selection.selected_tests),
        )
        return TestRunPlanResponse.from_entity(self._store.save_run_plan(plan))

    def get_selection(self, analysis_id) -> TestSelectionResponse:
        """Return saved test selection."""

        selection = self._store.get_selection(analysis_id)
        if selection is None:
            msg = f"Test selection for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return TestSelectionResponse.from_entity(selection)

    def execute_test_run(
        self,
        command: ExecuteTestRunCommand,
    ) -> TestRunResultResponse:
        """Execute a saved test run plan and persist result."""

        if self._runner is None:
            msg = "Test runner is not configured."
            raise ValidationError(msg)
        plan = self._store.get_run_plan(command.analysis_id)
        if plan is None:
            msg = f"Test run plan for analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)
        result = self._runner.run(plan, command.repository_path)
        return TestRunResultResponse.from_entity(self._store.save_run_result(result))

    def get_run_result(self, analysis_id) -> TestRunResultResponse:
        """Return saved test run result."""

        result = self._store.get_run_result(analysis_id)
        if result is None:
            msg = f"Test run result for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return TestRunResultResponse.from_entity(result)

    def ingest_test_results(
        self,
        analysis_id: UUID,
        content: str | bytes,
    ) -> TestRunResultResponse:
        """Ingest and persist test results from CI / JUnit report."""
        parser = JUnitReportParser()
        result = parser.parse(content, analysis_id)
        saved = self._store.save_run_result(result)
        return TestRunResultResponse.from_entity(saved)

