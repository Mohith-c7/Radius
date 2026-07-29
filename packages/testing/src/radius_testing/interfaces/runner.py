"""Test runner interfaces."""

from typing import Protocol

from radius_testing.domain.entities import TestCase, TestRunPlan


class TestCommandPlanner(Protocol):
    """Build structured argv plans without executing tests."""

    def plan(self, analysis_id, tests: tuple[TestCase, ...]) -> TestRunPlan:
        """Return a structured run plan."""


class TestRunner(Protocol):
    """Future test execution contract."""

    def run(self, plan: TestRunPlan) -> None:
        """Execute a structured test run plan."""
