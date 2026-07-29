"""SQLAlchemy testing store adapter."""

from uuid import UUID

from radius_shared.database import models as db_models
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from radius_testing.domain.entities import (
    SelectedTest,
    TestCase,
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

    def save_test_cases(self, tests: tuple[TestCase, ...]) -> tuple[TestCase, ...]:
        """Persist discovered test cases by path."""

        for test in tests:
            row = self._session.scalar(
                select(db_models.TestCase).where(
                    db_models.TestCase.path == test.path.value
                )
            )
            if row is None:
                row = db_models.TestCase(path=test.path.value)
                self._session.add(row)
            row.id = test.id
            row.name = test.name.value
            row.framework = test.framework.value
            row.test_type = test.test_type.value
            row.target_path = test.target_path.value if test.target_path else None
            row.test_metadata = dict(test.metadata)
        self._session.flush()
        return self.list_test_cases()

    def list_test_cases(self) -> tuple[TestCase, ...]:
        """Return known test cases."""

        rows = self._session.scalars(
            select(db_models.TestCase).order_by(db_models.TestCase.path)
        ).all()
        return tuple(self._test_case_to_domain(row) for row in rows)

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
        for selected in selection.selected_tests:
            test_row = self._session.scalar(
                select(db_models.TestCase).where(
                    db_models.TestCase.path == selected.test_case.path.value
                )
            )
            if test_row is None:
                self.save_test_cases((selected.test_case,))
                test_row = self._session.scalar(
                    select(db_models.TestCase).where(
                        db_models.TestCase.path == selected.test_case.path.value
                    )
                )
            self._session.add(
                db_models.SelectedTest(
                    selection_id=row.id,
                    test_case_id=test_row.id,
                    reason=selected.reason.value,
                )
            )
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
        return TestSelection(
            analysis_id=row.analysis_id,
            selected_tests=tuple(
                SelectedTest(
                    self._test_case_to_domain(selected.test_case),
                    TestSelectionReason(selected.reason),
                )
                for selected in sorted(
                    row.selected_tests,
                    key=lambda item: item.test_case.path,
                )
            ),
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
