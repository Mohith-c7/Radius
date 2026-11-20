"""In-memory testing infrastructure."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from radius_testing.domain.entities import (
    CaseOutcome,
    ReportedTestCase,
    TestCase,
    TestResultUpload,
    TestRunPlan,
    TestRunResult,
    TestSelection,
)
from radius_testing.domain.enums import TestRunStatus


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
        self._evidence_manifests: dict[UUID, dict] = {}
        self._verification_events: list[dict] = []

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
            flaky_files = {t.split("::", 1)[0].replace("\\", "/") for t in result.flaky_tests}
            duration = result.duration_ms // max(1, len(selection.selected_tests))
            self._history[result.analysis_id] = [
                {
                    "test_name": item.test_case.name.value,
                    "test_path": item.test_case.path.value,
                    "status": (
                        "failed"
                        if result.failed
                        # an ERROR/unfinished run is not evidence any file passed
                        else result.status.value
                        if result.status is not TestRunStatus.PASSED
                        else "flaky"
                        if item.test_case.path.value.replace("\\", "/") in flaky_files
                        else "passed"
                    ),
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

    def record_case_executions(
        self,
        analysis_id: UUID,
        cases: tuple[ReportedTestCase, ...],
        limit: int,
    ) -> int:
        """Append one history row per reported case, at most ``limit`` per analysis."""

        rows = self._history.setdefault(analysis_id, [])
        by_path = {row["test_path"]: row for row in rows}
        for case in cases:
            row = by_path.get(case.label[:500])
            if row is not None and case.outcome == CaseOutcome.FAILED:
                row["status"] = "failed"
        added = 0
        now = datetime.now(UTC).isoformat()
        for case in sorted(cases, key=lambda item: item.outcome != CaseOutcome.FAILED):
            path = case.label[:500]
            if len(rows) >= limit:
                break
            if not case.key[2] or path in by_path:
                continue
            row = {
                "test_name": case.key[2][:255],
                "test_path": path,
                "status": str(case.outcome),
                "duration_ms": 0,
                "timestamp": now,
                "failure_info": None,
                "coverage_percent": None,
                "framework": "junit",
            }
            rows.append(row)
            by_path[path] = row
            added += 1
        return added

    def list_test_samples(self, repository_id: UUID, limit: int = 5000) -> list[dict]:
        """Return history rows oldest first (the in-memory store is single-tenant)."""

        rows = [
            {
                "test_path": item["test_path"],
                "test_name": item["test_name"],
                "status": item["status"],
                "commit_sha": item.get("commit_sha"),
                "analysis_id": str(analysis_id),
            }
            for analysis_id, items in self._history.items()
            for item in items
        ]
        return rows[-limit:]

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
        report_slot_id: str = "legacy",
        run_id: str | None = None,
        run_attempt: int | None = None,
    ) -> TestResultUpload | None:
        """Return an earlier upload of the identical report body, if any."""

        for upload in self._uploads.get(analysis_id, ()):
            if (
                upload.body_sha256 == body_sha256
                and upload.report_slot_id == report_slot_id
                and upload.run_id == run_id
                and upload.run_attempt == run_attempt
            ):
                return upload
        return None

    def save_result_upload(self, upload: TestResultUpload) -> TestResultUpload:
        """Append one upload; an identical body is stored only once."""

        existing = self.get_result_upload(
            upload.analysis_id,
            upload.body_sha256,
            upload.report_slot_id,
            upload.run_id,
            upload.run_attempt,
        )
        if upload.run_id is not None:
            slot_use = next(
                (
                    item
                    for item in self._uploads.get(upload.analysis_id, ())
                    if item.run_id == upload.run_id
                    and item.run_attempt == upload.run_attempt
                    and item.report_slot_id == upload.report_slot_id
                ),
                None,
            )
            if slot_use is not None:
                if (
                    slot_use.body_sha256 != upload.body_sha256
                    or slot_use.analysis_id != upload.analysis_id
                ):
                    raise ValueError("REPLAY_CONFLICT")
                return slot_use
        if existing is not None:
            return existing
        self._uploads.setdefault(upload.analysis_id, []).append(upload)
        return upload

    def get_or_create_evidence_manifest(
        self,
        analysis_id: UUID,
        repository_id: UUID,
        head_sha: str,
        manifest: dict,
        digest_sha256: str,
    ) -> dict:
        existing = self._evidence_manifests.get(analysis_id)
        value = {
            "id": str(uuid4()),
            "analysis_id": str(analysis_id),
            "repository_id": str(repository_id),
            "head_sha": head_sha,
            "manifest": manifest,
            "digest_sha256": digest_sha256,
        }
        if existing is not None:
            if existing["digest_sha256"] != digest_sha256:
                raise ValueError("MANIFEST_IMMUTABLE")
            return existing
        self._evidence_manifests[analysis_id] = value
        return value

    def append_verification_event(
        self,
        upload_id: UUID,
        status: str,
        reason_code: str | None,
        verifier_version: str,
        policy_version: str,
        details: dict,
        attestation_digest: str | None = None,
        attestation_bundle: bytes | None = None,
    ) -> None:
        self._verification_events.append(
            {
                "upload_id": str(upload_id),
                "status": status,
                "reason_code": reason_code,
                "verifier_version": verifier_version,
                "policy_version": policy_version,
                "attestation_digest": attestation_digest,
                "attestation_bundle": attestation_bundle,
                "details": dict(details),
            }
        )

    def lock_result_uploads(self, analysis_id: UUID) -> None:
        """No-op: in-memory ingestion runs synchronously on one event loop."""

    def list_result_uploads(self, analysis_id: UUID) -> tuple[TestResultUpload, ...]:
        """Return all uploads for an analysis, oldest first."""
        events_by_id = {
            item["upload_id"]: item for item in self._verification_events
        }
        return tuple(
            replace(
                upload,
                provenance_status=events_by_id.get(str(upload.id), {}).get(
                    "status", upload.provenance_status
                ),
                provenance_reason_code=events_by_id.get(str(upload.id), {}).get(
                    "reason_code", upload.provenance_reason_code
                ),
            )
            for upload in self._uploads.get(analysis_id, ())
        )
