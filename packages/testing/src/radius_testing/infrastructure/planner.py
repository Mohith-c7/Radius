"""Structured test command planner."""

from uuid import UUID

from radius_testing.domain.entities import TestCase, TestRunPlan
from radius_testing.domain.enums import TestFramework


class StaticTestCommandPlanner:
    """Create argv-style plans without executing them."""

    def plan(self, analysis_id: UUID, tests: tuple[TestCase, ...]) -> TestRunPlan:
        """Return a structured run plan grouped by framework."""

        pytest_paths = tuple(
            test.path.value for test in tests if test.framework == TestFramework.PYTEST
        )
        command_plan: list[tuple[str, tuple[str, ...]]] = []
        if pytest_paths:
            command_plan.append(("pytest", pytest_paths))
        return TestRunPlan.pending(
            analysis_id=analysis_id,
            selected_tests=tests,
            command_plan=tuple(command_plan),
        )
