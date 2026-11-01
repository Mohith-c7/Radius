"""SQLAlchemy testing store adapter."""

from uuid import UUID

from radius_shared.database import models as db_models
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from radius_testing.domain.entities import (
    ReportedTestCase,
    SelectedTest,
    TestCase,
    TestResultUpload,
    TestRunPlan,
    TestRunResult,
    TestSelection,
)
from radius_testing.domain.enums import (
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
                )
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
        all_tests = self.list_test_cases()
        selected_paths = {selected.test_case.path.value for selected in selected_tests}
        skipped_tests = tuple(t for t in all_tests if t.path.value not in selected_paths)
        total_count = max(len(all_tests), len(selected_tests))
        return TestSelection(
            analysis_id=row.analysis_id,
            selected_tests=selected_tests,
            skipped_tests=skipped_tests,
            total_discovered_count=total_count,
            created_at=row.created_at,
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
            test.path.value: test for test in self.list_test_cases()
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
        """Persist executed test run result."""

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
            )
        )
        self._session.flush()
        return result

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
            status=(
                TestRunStatus.FAILED
                if row.failed > 0
                else TestRunStatus.PASSED
            ),
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
    ) -> TestResultUpload | None:
        """Return an earlier upload of the identical report body, if any."""

        row = self._session.scalar(
            select(db_models.TestResultUpload).where(
                db_models.TestResultUpload.analysis_id == analysis_id,
                db_models.TestResultUpload.body_sha256 == body_sha256,
            )
        )
        return self._upload_to_domain(row) if row is not None else None

    def save_result_upload(self, upload: TestResultUpload) -> TestResultUpload:
        """Append one upload; an identical body is stored only once.

        The (analysis_id, body_sha256) unique constraint makes concurrent
        replays of the same report collapse into one row.
        """

        existing = self.get_result_upload(upload.analysis_id, upload.body_sha256)
        if existing is not None:
            return existing
        result = upload.result
        row = db_models.TestResultUpload(
            id=upload.id,
            analysis_id=upload.analysis_id,
            commit_sha=upload.commit_sha,
            body_sha256=upload.body_sha256,
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
            existing = self.get_result_upload(upload.analysis_id, upload.body_sha256)
            if existing is None:
                raise
            return existing
        return upload

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
        return tuple(self._upload_to_domain(row) for row in rows)

    @staticmethod
    def _upload_to_domain(row: db_models.TestResultUpload) -> TestResultUpload:
        return TestResultUpload(
            id=row.id,
            analysis_id=row.analysis_id,
            commit_sha=row.commit_sha,
            body_sha256=row.body_sha256,
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
