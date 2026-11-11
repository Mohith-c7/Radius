"""Testing persistence interfaces."""

from typing import Protocol
from uuid import UUID

from radius_testing.domain.entities import (
    TestCase,
    TestResultUpload,
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

    def save_run_result(self, result: TestRunResult, retry_index: int = 0) -> TestRunResult:
        """Persist test execution result, optionally specifying retry index."""

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
    def get_result_upload(
        self,
        analysis_id: UUID,
        body_sha256: str,
    ) -> TestResultUpload | None:
        """Return an earlier upload of the identical report body, if any."""

    def save_result_upload(self, upload: TestResultUpload) -> TestResultUpload:
        """Persist one CI report upload (uploads accumulate, never replace).

        Saving a body hash that is already stored for the analysis returns the
        stored upload unchanged.
        """

    def lock_result_uploads(self, analysis_id: UUID) -> None:
        """Serialise result ingestion for one analysis until the transaction ends.

        Concurrent uploads must not each compute the verdict from only their
        own upload (the last writer could then drop another shard's failure).
        """

    def list_result_uploads(self, analysis_id: UUID) -> tuple[TestResultUpload, ...]:
        """Return all uploads for an analysis, oldest first."""
