"""In-memory testing infrastructure."""

from datetime import UTC, datetime
from uuid import UUID

from radius_testing.domain.entities import (
    TestCase,
    TestResultUpload,
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
        self._history: dict[UUID, list[dict]] = {}  # analysis_id -> history
        self._statistics: dict[UUID, dict] = {}  # analysis_id -> statistics
        self._recent: dict[UUID, list[dict]] = {}  # analysis_id -> recent executions
        self._uploads: dict[UUID, list[TestResultUpload]] = {}

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
        selection = self._selections.get(result.analysis_id)
        if selection is not None and not self._history.get(result.analysis_id):
            status = "failed" if result.failed else "passed"
            duration = result.duration_ms // max(1, len(selection.selected_tests))
            self._history[result.analysis_id] = [
                {
                    "test_name": item.test_case.name.value,
                    "test_path": item.test_case.path.value,
                    "status": status,
                    "duration_ms": duration,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "failure_info": result.output if result.failed else None,
                    "coverage_percent": result.coverage_percent,
                    "framework": item.test_case.framework.value,
                }
                for item in selection.selected_tests
            ]
        return result

    def get_run_result(self, analysis_id: UUID) -> TestRunResult | None:
        """Return executed test run result."""

        return self._results.get(analysis_id)

    def save_test_history(self, analysis_id: UUID, history: list[dict]) -> None:
        """Persist test execution history for an analysis."""

        self._history[analysis_id] = history

    def get_test_history(self, analysis_id: UUID) -> list[dict]:
        """Return test execution history for an analysis."""

        return self._history.get(analysis_id, [])

    def save_test_statistics(self, analysis_id: UUID, statistics: dict) -> None:
        """Persist test execution statistics for an analysis."""

        self._statistics[analysis_id] = statistics

    def get_test_statistics(self, analysis_id: UUID) -> dict:
        """Return test execution statistics for an analysis."""
        history = self._history.get(analysis_id, [])
        if history:
            total = len(history)
            passed = sum(item["status"] == "passed" for item in history)
            failed = sum(item["status"] == "failed" for item in history)
            return {
                "total_runs": total, "pass_count": passed, "failure_count": failed,
                "pass_rate": round(passed * 100 / total, 2),
                "failure_rate": round(failed * 100 / total, 2),
                "average_duration_ms": round(sum(item["duration_ms"] for item in history) / total, 2),
                "recent_failures": failed,
                "last_execution": max(item["timestamp"] for item in history),
            }
        return self._statistics.get(analysis_id, {
            "total_runs": 0,
            "pass_count": 0,
            "failure_count": 0,
            "pass_rate": 0.0,
            "failure_rate": 0.0,
            "average_duration_ms": 0,
            "recent_failures": 0,
            "last_execution": None,
        })

    def save_recent_executions(self, analysis_id: UUID, executions: list[dict]) -> None:
        """Persist recent test executions for an analysis."""

        self._recent[analysis_id] = executions

    def get_recent_executions(
        self, repository_id: UUID | None = None, limit: int = 50
    ) -> list[dict]:
        """Return recent test executions across analyses."""

        # For in-memory, just return all stored recent executions
        # This is a simplification - in a real system we'd aggregate across analyses
        result = []
        for executions in self._recent.values():
            result.extend(
                item
                for item in executions
                if repository_id is None
                or str(item.get("repository_id")) == str(repository_id)
            )
        # Sort by timestamp descending and limit
        result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return result[:limit]
    def get_result_upload(
        self,
        analysis_id: UUID,
        body_sha256: str,
    ) -> TestResultUpload | None:
        """Return an earlier upload of the identical report body, if any."""

        for upload in self._uploads.get(analysis_id, ()):
            if upload.body_sha256 == body_sha256:
                return upload
        return None

    def save_result_upload(self, upload: TestResultUpload) -> TestResultUpload:
        """Append one upload; an identical body is stored only once."""

        existing = self.get_result_upload(upload.analysis_id, upload.body_sha256)
        if existing is not None:
            return existing
        self._uploads.setdefault(upload.analysis_id, []).append(upload)
        return upload

    def lock_result_uploads(self, analysis_id: UUID) -> None:
        """No-op: in-memory ingestion runs synchronously on one event loop."""

    def list_result_uploads(self, analysis_id: UUID) -> tuple[TestResultUpload, ...]:
        """Return all uploads for an analysis, oldest first."""

        return tuple(self._uploads.get(analysis_id, ()))
