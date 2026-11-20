"""SQLAlchemy testing store adapter."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from radius_shared.database import models as db_models
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from radius_testing.domain.entities import (
    CaseOutcome,
    ReportedTestCase,
    SelectedTest,
    TestCase,
    TestResultUpload,
    TestRunPlan,
    TestRunResult,
    TestSelection,
    TestSelectionDecision,
)
from radius_testing.domain.enums import (
    TestDecision,
    TestFramework,
    TestRunStatus,
    TestSelectionReason,
    TestType,
)
from radius_testing.domain.value_objects import SourcePath, TestName, TestPath


class SqlAlchemyTestStore:
    """Persist discovered tests, selections, and run plans in SQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_test_cases(
        self,
        tests: tuple[TestCase, ...],
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Persist discovered test cases by (repository, path)."""

        for test in tests:
            row = self._session.scalar(
                self._by_path(repository_id, test.path.value)
            )
            if row is None:
                row = db_models.TestCase(
                    id=test.id,
                    repository_id=repository_id,
                    path=test.path.value,
                )
                self._session.add(row)
            row.name = test.name.value
            row.framework = test.framework.value
            row.test_type = test.test_type.value
            row.target_path = test.target_path.value if test.target_path else None
            row.test_metadata = dict(test.metadata)
        self._session.flush()
        return self.list_test_cases(repository_id)

    def list_test_cases(
        self,
        repository_id: UUID | None = None,
    ) -> tuple[TestCase, ...]:
        """Return known test cases, scoped to one repository when given."""

        query = select(db_models.TestCase).order_by(db_models.TestCase.path)
        if repository_id is not None:
            query = query.where(db_models.TestCase.repository_id == repository_id)
        rows = self._session.scalars(query).all()
        return tuple(self._test_case_to_domain(row) for row in rows)

    def _repository_test_cases(self, analysis_id: UUID) -> tuple[TestCase, ...]:
        """Test cases of the analysed repository only, never another repository's.

        Same scoping as ``save_selection``: when the analysis has no repository the
        selection's test cases were stored with a NULL repository, so only those are
        returned (``list_test_cases(None)`` would return every repository's tests).
        """

        repository_id = self._analysis_repository_id(analysis_id)
        query = select(db_models.TestCase).order_by(db_models.TestCase.path)
        if repository_id is None:
            query = query.where(db_models.TestCase.repository_id.is_(None))
        else:
            query = query.where(db_models.TestCase.repository_id == repository_id)
        return tuple(self._test_case_to_domain(row) for row in self._session.scalars(query))

    @staticmethod
    def _by_path(repository_id: UUID | None, path: str):
        query = select(db_models.TestCase).where(db_models.TestCase.path == path)
        if repository_id is None:
            return query.where(db_models.TestCase.repository_id.is_(None))
        return query.where(db_models.TestCase.repository_id == repository_id)

    def _analysis_repository_id(self, analysis_id: UUID) -> UUID | None:
        analysis = self._session.get(db_models.Analysis, analysis_id)
        return analysis.repository_id if analysis is not None else None

    def save_selection(self, selection: TestSelection) -> TestSelection:
        """Persist test selection for one analysis."""

        self._session.execute(
            delete(db_models.TestSelection).where(
                db_models.TestSelection.analysis_id == selection.analysis_id
            )
        )
        self._session.flush()
        row = db_models.TestSelection(
            analysis_id=selection.analysis_id,
            created_at=selection.created_at,
        )
        self._session.add(row)
        self._session.flush()
        repository_id = self._analysis_repository_id(selection.analysis_id)
        for selected in selection.selected_tests:
            path = selected.test_case.path.value
            test_row = self._session.scalar(self._by_path(repository_id, path))
            if test_row is None:
                self.save_test_cases((selected.test_case,), repository_id)
                test_row = self._session.scalar(self._by_path(repository_id, path))
            self._session.add(
                db_models.SelectedTest(
                    selection_id=row.id,
                    test_case_id=test_row.id,
                    reason=selected.reason.value,
                )
            )
        if selection.skipped_tests:
            self.save_test_cases(selection.skipped_tests, repository_id)
        for decision in selection.decisions:
            # Test cases are repository-scoped (migration 0005): never look one
            # up by path alone, or another repository's row could be linked.
            decision_path = decision.test_case.path.value
            test_row = self._session.scalar(self._by_path(repository_id, decision_path))
            if test_row is None:
                self.save_test_cases((decision.test_case,), repository_id)
                test_row = self._session.scalar(self._by_path(repository_id, decision_path))
            self._session.add(db_models.TestSelectionEvidence(
                selection_id=row.id, test_case_id=test_row.id,
                decision=decision.decision.value,
                evidence_sources=list(decision.evidence_sources),
                evidence_details=list(decision.evidence_details),
                relevance_score=decision.relevance_score, reason=decision.reason,
            ))
        self._session.flush()
        saved = self.get_selection(selection.analysis_id)
        if saved is None:
            msg = "Test selection could not be saved."
            raise RuntimeError(msg)
        return saved

    def get_selection(self, analysis_id: UUID) -> TestSelection | None:
        """Return saved test selection."""

        row = self._session.scalar(
            select(db_models.TestSelection)
            .where(db_models.TestSelection.analysis_id == analysis_id)
            .options(
                selectinload(db_models.TestSelection.selected_tests).selectinload(
                    db_models.SelectedTest.test_case
                ),
                selectinload(db_models.TestSelection.decisions).selectinload(
                    db_models.TestSelectionEvidence.test_case
                ),
            )
        )
        if row is None:
            return None
        selected_tests = tuple(
            SelectedTest(
                self._test_case_to_domain(selected.test_case),
                TestSelectionReason(selected.reason),
            )
            for selected in sorted(
                row.selected_tests,
                key=lambda item: item.test_case.path,
            )
        )
        # Skipped tests and the total are scoped to the analysed repository: test
        # cases of other repositories (and other organizations) never appear here.
        all_tests = self._repository_test_cases(row.analysis_id)
        selected_paths = {selected.test_case.path.value for selected in selected_tests}
        skipped_tests = tuple(t for t in all_tests if t.path.value not in selected_paths)
        total_count = max(len(all_tests), len(selected_tests))
        return TestSelection(
            analysis_id=row.analysis_id,
            selected_tests=selected_tests,
            skipped_tests=skipped_tests,
            total_discovered_count=total_count,
            created_at=row.created_at,
            decisions=tuple(
                TestSelectionDecision(
                    test_case=self._test_case_to_domain(item.test_case),
                    decision=TestDecision(item.decision),
                    evidence_sources=tuple(item.evidence_sources or ()),
                    evidence_details=tuple(item.evidence_details or ()),
                    relevance_score=float(item.relevance_score), reason=item.reason,
                )
                for item in sorted(row.decisions, key=lambda item: item.test_case.path)
            ),
        )

    def save_run_plan(self, plan: TestRunPlan) -> TestRunPlan:
        """Persist structured run plan."""

        self._session.execute(
            delete(db_models.TestRunPlan).where(
                db_models.TestRunPlan.analysis_id == plan.analysis_id
            )
        )
        self._session.add(
            db_models.TestRunPlan(
                id=plan.id,
                analysis_id=plan.analysis_id,
                status=plan.status.value,
                selected_test_paths=[test.path.value for test in plan.selected_tests],
                command_plan=[
                    [command, list(args)] for command, args in plan.command_plan
                ],
                created_at=plan.created_at,
            )
        )
        self._session.flush()
        return plan

    def get_run_plan(self, analysis_id: UUID) -> TestRunPlan | None:
        """Return saved run plan."""

        row = self._session.scalar(
            select(db_models.TestRunPlan).where(
                db_models.TestRunPlan.analysis_id == analysis_id
            )
        )
        if row is None:
            return None
        tests = {
            test.path.value: test
            for test in self._repository_test_cases(row.analysis_id)
        }
        return TestRunPlan(
            id=row.id,
            analysis_id=row.analysis_id,
            status=TestRunStatus(row.status),
            selected_tests=tuple(
                tests[path]
                for path in row.selected_test_paths
                if path in tests
            ),
            command_plan=tuple(
                (command, tuple(args)) for command, args in row.command_plan
            ),
            created_at=row.created_at,
        )

    def save_run_result(self, result: TestRunResult) -> TestRunResult:
        """Persist executed test run result and history record."""

        # Persist the main test run result (upsert pattern - replace per analysis)
        self._session.execute(
            delete(db_models.TestRun).where(
                db_models.TestRun.analysis_id == result.analysis_id
            )
        )
        self._session.add(
            db_models.TestRun(
                id=result.id,
                analysis_id=result.analysis_id,
                framework="mixed",
                total_tests=result.total_tests,
                passed=result.passed,
                failed=result.failed,
                skipped=result.skipped,
                duration_ms=result.duration_ms,
                coverage_percent=result.coverage_percent,
                status=result.status.value,
            )
        )
        self._session.flush()

        # A runner currently returns an aggregate result. Record one result per
        # selected test; future JUnit adapters can provide per-case results with
        # the same idempotency key (analysis_id, test_path).
        analysis = self._session.get(db_models.Analysis, result.analysis_id)
        selection = self.get_selection(result.analysis_id)
        if analysis is not None and selection is not None:
            branch = analysis.pull_request.source_branch if analysis.pull_request else None
            pr_id = analysis.pull_request.github_pr_number if analysis.pull_request else None
            duration_per_test = result.duration_ms // max(1, len(selection.selected_tests))
            flaky_files = {_norm_path(t.split("::", 1)[0]) for t in result.flaky_tests}
            for item in selection.selected_tests:
                path = item.test_case.path.value
                status = _history_status(result, path, flaky_files)
                existing = self._session.scalar(select(db_models.TestExecutionHistory).where(
                    db_models.TestExecutionHistory.analysis_id == result.analysis_id,
                    db_models.TestExecutionHistory.test_path == path,
                ))
                if existing is None:
                    self._session.add(db_models.TestExecutionHistory(
                        test_name=item.test_case.name.value, test_path=path,
                        repository_id=analysis.repository_id, analysis_id=result.analysis_id,
                        commit_sha=analysis.commit_sha, pr_id=pr_id, branch=branch,
                        status=status, duration_ms=duration_per_test,
                        timestamp=datetime.now(UTC),
                        failure_info=result.output if result.failed else None,
                        coverage_percent=result.coverage_percent,
                        framework=item.test_case.framework.value,
                    ))
        self._session.flush()

        return result

    def record_case_executions(
        self,
        analysis_id: UUID,
        cases: tuple[ReportedTestCase, ...],
        limit: int,
    ) -> int:
        """Bulk-insert one history row per reported case (capped per analysis).

        Rows are keyed by the case label (``file::class::name``), which never
        equals a selected test file's path, so the per-file rows written by
        :meth:`save_run_result` are untouched. Failed cases are recorded first
        when the cap is reached.
        """

        if limit <= 0 or not cases:
            return 0
        analysis = self._session.get(db_models.Analysis, analysis_id)
        if analysis is None:
            return 0
        history = db_models.TestExecutionHistory
        existing = dict(
            self._session.execute(
                select(history.test_path, history.status).where(
                    history.analysis_id == analysis_id
                )
            ).all()
        )
        failed_paths = {_case_path(case) for case in cases if case.outcome == CaseOutcome.FAILED}
        newly_failed = sorted(
            path for path in failed_paths if path in existing and existing[path] != "failed"
        )
        if newly_failed:
            # Failures are sticky: a case first seen passing, then failing, is failed.
            self._session.execute(
                update(history)
                .where(history.analysis_id == analysis_id, history.test_path.in_(newly_failed))
                .values(status="failed")
            )
        budget = limit - len(existing)
        if budget <= 0:
            self._session.flush()
            return 0
        pull_request = analysis.pull_request
        now = datetime.now(UTC)
        seen = set(existing)
        rows: list[dict[str, Any]] = []
        ordered = sorted(cases, key=lambda case: case.outcome != CaseOutcome.FAILED)
        for case in ordered:
            if len(rows) >= budget:
                break
            path = _case_path(case)
            if not case.key[2] or not path or path in seen:
                continue
            seen.add(path)
            rows.append({
                "test_name": case.key[2][:255],
                "test_path": path,
                "repository_id": analysis.repository_id,
                "analysis_id": analysis_id,
                "commit_sha": analysis.commit_sha,
                "pr_id": pull_request.github_pr_number if pull_request else None,
                "branch": pull_request.source_branch if pull_request else None,
                "status": str(case.outcome),
                "duration_ms": 0,
                "timestamp": now,
                "framework": "junit",
            })
        if rows:
            self._session.execute(insert(history), rows)
        self._session.flush()
        return len(rows)

    def get_run_result(self, analysis_id: UUID) -> TestRunResult | None:
        """Return executed test run result."""

        row = self._session.scalar(
            select(db_models.TestRun).where(
                db_models.TestRun.analysis_id == analysis_id
            )
        )
        if row is None:
            return None
        return TestRunResult(
            id=row.id,
            analysis_id=row.analysis_id,
            status=_stored_run_status(row),
            total_tests=row.total_tests,
            passed=row.passed,
            failed=row.failed,
            skipped=row.skipped,
            duration_ms=row.duration_ms,
            coverage_percent=(
                float(row.coverage_percent)
                if row.coverage_percent is not None
                else None
            ),
        )

    def get_result_upload(
        self,
        analysis_id: UUID,
        body_sha256: str,
        report_slot_id: str = "legacy",
        run_id: str | None = None,
        run_attempt: int | None = None,
    ) -> TestResultUpload | None:
        """Return an earlier upload of the identical report body, if any."""

        criteria = [
            db_models.TestResultUpload.analysis_id == analysis_id,
            db_models.TestResultUpload.body_sha256 == body_sha256,
            db_models.TestResultUpload.report_slot_id == report_slot_id,
        ]
        criteria.append(
            db_models.TestResultUpload.run_id.is_(None)
            if run_id is None
            else db_models.TestResultUpload.run_id == run_id
        )
        criteria.append(
            db_models.TestResultUpload.run_attempt.is_(None)
            if run_attempt is None
            else db_models.TestResultUpload.run_attempt == run_attempt
        )
        row = self._session.scalar(
            select(db_models.TestResultUpload).where(*criteria)
        )
        return self._upload_to_domain(row) if row is not None else None

    def save_result_upload(self, upload: TestResultUpload) -> TestResultUpload:
        """Append one upload; an identical body is stored only once.

        The (analysis_id, body_sha256) unique constraint makes concurrent
        replays of the same report collapse into one row.
        """

        existing = self.get_result_upload(
            upload.analysis_id,
            upload.body_sha256,
            upload.report_slot_id,
            upload.run_id,
            upload.run_attempt,
        )
        if existing is not None:
            if (
                existing.run_id != upload.run_id
                or existing.run_attempt != upload.run_attempt
                or existing.manifest_digest != upload.manifest_digest
            ):
                raise ValueError("REPLAY_CONFLICT")
            return existing
        if upload.run_id is not None:
            slot_use = self._session.scalar(
                select(db_models.TestResultUpload).where(
                    db_models.TestResultUpload.repository_id == upload.repository_id,
                    db_models.TestResultUpload.run_id == upload.run_id,
                    db_models.TestResultUpload.run_attempt == upload.run_attempt,
                    db_models.TestResultUpload.report_slot_id == upload.report_slot_id,
                )
            )
            if slot_use is not None:
                raise ValueError("REPLAY_CONFLICT")
        if upload.attestation_digest is not None:
            reused = self._session.scalar(
                select(db_models.TestResultUpload).where(
                    db_models.TestResultUpload.repository_id == upload.repository_id,
                    db_models.TestResultUpload.attestation_digest == upload.attestation_digest,
                )
            )
            if reused is not None:
                raise ValueError("REPLAY_CONFLICT")
        result = upload.result
        row = db_models.TestResultUpload(
            id=upload.id,
            analysis_id=upload.analysis_id,
            commit_sha=upload.commit_sha,
            body_sha256=upload.body_sha256,
            repository_id=upload.repository_id,
            report_slot_id=upload.report_slot_id,
            run_id=upload.run_id,
            run_attempt=upload.run_attempt,
            manifest_id=upload.manifest_id,
            manifest_digest=upload.manifest_digest,
            artifact_bytes=upload.artifact_bytes,
            attestation_bundle=upload.attestation_bundle,
            attestation_digest=upload.attestation_digest,
            provenance_status=upload.provenance_status,
            provenance_reason_code=upload.provenance_reason_code,
            status=result.status.value,
            total_tests=result.total_tests,
            passed=result.passed,
            failed=result.failed,
            skipped=result.skipped,
            duration_ms=result.duration_ms,
            coverage_percent=result.coverage_percent,
            output=result.output,
            cases=[
                {
                    "file": case.file,
                    "classname": case.classname,
                    "name": case.name,
                    "outcome": case.outcome,
                }
                for case in upload.cases
            ],
            created_at=upload.created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self.get_result_upload(
                upload.analysis_id,
                upload.body_sha256,
                upload.report_slot_id,
                upload.run_id,
                upload.run_attempt,
            )
            if existing is None:
                raise ValueError("REPLAY_CONFLICT") from None
            if (
                existing.commit_sha != upload.commit_sha
                or existing.manifest_digest != upload.manifest_digest
            ):
                raise ValueError("REPLAY_CONFLICT") from None
            return existing
        return upload

    def get_or_create_evidence_manifest(
        self,
        analysis_id: UUID,
        repository_id: UUID,
        head_sha: str,
        manifest: dict,
        digest_sha256: str,
    ) -> dict:
        """Persist one immutable manifest per analysis, serialized by row lock."""

        self._session.execute(
            select(db_models.Analysis.id)
            .where(db_models.Analysis.id == analysis_id)
            .with_for_update()
        )
        row = self._session.scalar(
            select(db_models.TestEvidenceManifest).where(
                db_models.TestEvidenceManifest.analysis_id == analysis_id
            )
        )
        if row is not None:
            if row.digest_sha256 != digest_sha256:
                raise ValueError("MANIFEST_IMMUTABLE")
        else:
            row = db_models.TestEvidenceManifest(
                analysis_id=analysis_id,
                repository_id=repository_id,
                head_sha=head_sha.lower(),
                manifest_version=1,
                canonical_manifest=manifest,
                digest_sha256=digest_sha256,
                created_at=datetime.now(UTC),
            )
            self._session.add(row)
            self._session.flush()
        return {
            "id": str(row.id),
            "analysis_id": str(row.analysis_id),
            "repository_id": str(row.repository_id),
            "head_sha": row.head_sha,
            "manifest": row.canonical_manifest,
            "digest_sha256": row.digest_sha256,
        }

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
        """Append a verification event without mutating earlier event rows."""

        if attestation_digest is not None:
            previous = self._session.scalar(
                select(db_models.TestEvidenceVerificationEvent).where(
                    db_models.TestEvidenceVerificationEvent.upload_id == upload_id,
                    db_models.TestEvidenceVerificationEvent.attestation_digest
                    == attestation_digest,
                    db_models.TestEvidenceVerificationEvent.verifier_version
                    == verifier_version,
                    db_models.TestEvidenceVerificationEvent.policy_version
                    == policy_version,
                )
            )
            if previous is not None:
                return

        self._session.add(
            db_models.TestEvidenceVerificationEvent(
                upload_id=upload_id,
                status=status,
                reason_code=reason_code,
                verifier_version=verifier_version,
                policy_version=policy_version,
                attestation_digest=attestation_digest,
                attestation_bundle=attestation_bundle,
                details=details,
                verified_at=datetime.now(UTC),
            )
        )
        self._session.flush()

    def lock_result_uploads(self, analysis_id: UUID) -> None:
        """Take a row lock on the analysis for the rest of the transaction.

        ``SELECT ... FOR UPDATE`` on PostgreSQL; SQLite ignores the clause but
        already serialises writers.
        """

        self._session.execute(
            select(db_models.Analysis.id)
            .where(db_models.Analysis.id == analysis_id)
            .with_for_update()
        )

    def list_result_uploads(self, analysis_id: UUID) -> tuple[TestResultUpload, ...]:
        """Return all uploads for an analysis, oldest first."""

        rows = self._session.scalars(
            select(db_models.TestResultUpload)
            .where(db_models.TestResultUpload.analysis_id == analysis_id)
            .order_by(db_models.TestResultUpload.created_at, db_models.TestResultUpload.id)
        ).all()
        latest_events: dict[UUID, Any] = {}
        if rows:
            events = self._session.scalars(
                select(db_models.TestEvidenceVerificationEvent)
                .where(
                    db_models.TestEvidenceVerificationEvent.upload_id.in_(
                        [row.id for row in rows]
                    )
                )
                .order_by(
                    db_models.TestEvidenceVerificationEvent.verified_at,
                    db_models.TestEvidenceVerificationEvent.id,
                )
            ).all()
            latest_events = {event.upload_id: event for event in events}
        return tuple(
            self._upload_to_domain(row, latest_events.get(row.id)) for row in rows
        )

    @staticmethod
    def _upload_to_domain(row: db_models.TestResultUpload, event=None) -> TestResultUpload:
        return TestResultUpload(
            id=row.id,
            analysis_id=row.analysis_id,
            commit_sha=row.commit_sha,
            body_sha256=row.body_sha256,
            repository_id=row.repository_id,
            report_slot_id=row.report_slot_id,
            run_id=row.run_id,
            run_attempt=row.run_attempt,
            manifest_id=row.manifest_id,
            manifest_digest=row.manifest_digest,
            artifact_bytes=row.artifact_bytes,
            attestation_bundle=row.attestation_bundle,
            attestation_digest=row.attestation_digest,
            provenance_status=event.status if event is not None else row.provenance_status,
            provenance_reason_code=(
                event.reason_code if event is not None else row.provenance_reason_code
            ),
            result=TestRunResult(
                id=row.id,
                analysis_id=row.analysis_id,
                status=TestRunStatus(row.status),
                total_tests=row.total_tests,
                passed=row.passed,
                failed=row.failed,
                skipped=row.skipped,
                duration_ms=row.duration_ms,
                coverage_percent=(
                    float(row.coverage_percent)
                    if row.coverage_percent is not None
                    else None
                ),
                output=row.output or "",
            ),
            cases=tuple(
                ReportedTestCase(
                    file=item.get("file"),
                    classname=item.get("classname"),
                    name=item.get("name"),
                    outcome=item.get("outcome", "passed"),
                )
                for item in (row.cases or ())
                if isinstance(item, dict)
            ),
            created_at=row.created_at,
        )

    @staticmethod
    def _test_case_to_domain(row: db_models.TestCase) -> TestCase:
        return TestCase(
            id=row.id,
            name=TestName(row.name),
            path=TestPath(row.path),
            framework=TestFramework(row.framework),
            test_type=TestType(row.test_type),
            target_path=SourcePath(row.target_path) if row.target_path else None,
            metadata=dict(row.test_metadata or {}),
        )
    def get_test_history(self, analysis_id: UUID) -> list[dict]:
        """Return test execution history for an analysis."""

        rows = self._history_rows(analysis_id)

        return [
            {
                "id": str(row.id),
                "test_name": row.test_name,
                "test_path": row.test_path,
                "status": row.status,
                "duration_ms": row.duration_ms,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "failure_info": row.failure_info,
                "coverage_percent": float(row.coverage_percent) if row.coverage_percent else None,
                "framework": row.framework,
                "branch": row.branch,
                "commit_sha": row.commit_sha,
                "pr_id": row.pr_id,
            }
            for row in rows
        ]

    def get_test_statistics(self, analysis_id: UUID) -> dict:
        """Return test execution statistics for an analysis."""

        rows = self._history_rows(analysis_id)

        if not rows:
            return {
                "total_runs": 0,
                "pass_count": 0,
                "failure_count": 0,
                "pass_rate": 0.0,
                "failure_rate": 0.0,
                "average_duration_ms": 0,
                "recent_failures": 0,
                "last_execution": None,
            }

        total_runs = len(rows)
        pass_count = sum(1 for row in rows if row.status == "passed")
        failure_count = sum(1 for row in rows if row.status == "failed")
        pass_rate = (pass_count / total_runs) * 100 if total_runs > 0 else 0.0
        failure_rate = (failure_count / total_runs) * 100 if total_runs > 0 else 0.0

        total_duration = sum(row.duration_ms for row in rows if row.duration_ms)
        average_duration_ms = total_duration / total_runs if total_runs > 0 else 0

        recent_failures = sum(
            1 for row in rows if row.status == "failed"
        )

        last_execution = max(rows, key=lambda r: r.timestamp) if rows else None
        last_exec_time = (
            last_execution.timestamp.isoformat() if last_execution and last_execution.timestamp else None
        )

        return {
            "total_runs": total_runs,
            "pass_count": pass_count,
            "failure_count": failure_count,
            "pass_rate": round(pass_rate, 2),
            "failure_rate": round(failure_rate, 2),
            "average_duration_ms": round(average_duration_ms, 2),
            "recent_failures": recent_failures,
            "last_execution": last_exec_time,
        }

    def _history_rows(self, analysis_id: UUID):
        """Return historical records for the analysis' tests in its repository."""

        analysis = self._session.get(db_models.Analysis, analysis_id)
        selection = self.get_selection(analysis_id)
        if analysis is None or selection is None or not selection.selected_tests:
            # Nothing selected: the analysis' own rows (every uploaded case).
            return self._session.scalars(
                select(db_models.TestExecutionHistory).where(
                    db_models.TestExecutionHistory.analysis_id == analysis_id
                ).order_by(db_models.TestExecutionHistory.timestamp.desc())
            ).all()
        paths = [item.test_case.path.value for item in selection.selected_tests]
        return self._session.scalars(
            select(db_models.TestExecutionHistory).where(
                db_models.TestExecutionHistory.repository_id == analysis.repository_id,
                db_models.TestExecutionHistory.test_path.in_(paths),
            ).order_by(db_models.TestExecutionHistory.timestamp.desc())
        ).all()

    def list_test_samples(self, repository_id: UUID, limit: int = 5000) -> list[dict]:
        """Return the newest ``limit`` history rows of a repository, oldest first.

        Ordered by (timestamp, id) so equal timestamps still give a stable order.
        """

        rows = self._session.scalars(
            select(db_models.TestExecutionHistory)
            .where(db_models.TestExecutionHistory.repository_id == repository_id)
            .order_by(
                db_models.TestExecutionHistory.timestamp.desc(),
                db_models.TestExecutionHistory.id.desc(),
            )
            .limit(limit)
        ).all()
        return [
            {
                "test_path": row.test_path,
                "test_name": row.test_name,
                "status": row.status,
                "commit_sha": row.commit_sha,
                "analysis_id": str(row.analysis_id),
            }
            for row in reversed(rows)
        ]

    def get_recent_executions(
        self, repository_id: UUID | None = None, limit: int = 50
    ) -> list[dict]:
        """Return recent test executions across analyses."""

        from radius_shared.database.models import Analysis  # type: ignore

        query = select(db_models.TestExecutionHistory).order_by(
            db_models.TestExecutionHistory.timestamp.desc()
        )

        if repository_id is not None:
            query = query.join(
                Analysis, db_models.TestExecutionHistory.analysis_id == Analysis.id
            ).where(Analysis.repository_id == repository_id)

        rows = self._session.scalars(query.limit(limit)).all()

        return [
            {
                "id": str(row.id),
                "test_name": row.test_name,
                "test_path": row.test_path,
                "repository_id": str(row.repository_id) if row.repository_id else None,
                "status": row.status,
                "duration_ms": row.duration_ms,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "branch": row.branch,
                "commit_sha": row.commit_sha,
                "pr_id": row.pr_id,
            }
            for row in rows
        ]


def _case_path(case: ReportedTestCase) -> str:
    """History key of one reported case (column is 500 characters)."""

    return case.label[:500]


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _history_status(result: TestRunResult, path: str, flaky_files: set[str]) -> str:
    """History status of one selected test file for an aggregate result.

    ``flaky`` is only recorded when nothing stably failed (conservative: a
    stable failure anywhere keeps every file ``failed``, as before F-11).
    """

    if result.failed:
        return "failed"
    if result.status is not TestRunStatus.PASSED:
        # An ERROR (or otherwise unfinished) run is not evidence that any file
        # passed; recording "passed" here would feed history and flakiness.
        return result.status.value
    if _norm_path(path) in flaky_files:
        return "flaky"
    return "passed"


def _stored_run_status(row: db_models.TestRun) -> TestRunStatus:
    """Status of a stored run.

    Rows written before ``test_runs.status`` existed have NULL there; for those
    the old derivation (failed > 0 -> FAILED, else PASSED) is kept, except that
    a run that recorded no outcome at all is ERROR, never PASSED.
    """

    if row.status:
        return TestRunStatus(row.status)
    if row.failed > 0:
        return TestRunStatus.FAILED
    if row.passed == 0 and row.total_tests == 0:
        return TestRunStatus.ERROR
    return TestRunStatus.PASSED
