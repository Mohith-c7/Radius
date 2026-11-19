"""SQL test store: tenant-scoped selections and runs that never read back as passed."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from radius_shared.database import models as db
from radius_shared.database.base import Base
from radius_shared.database.enums import AnalysisStatus, RepositoryVisibility
from radius_testing.domain import (
    SelectedTest,
)
from radius_testing.domain import (
    TestCase as RTestCase,
)
from radius_testing.domain import (
    TestFramework as RTestFramework,
)
from radius_testing.domain import (
    TestName as RTestName,
)
from radius_testing.domain import (
    TestPath as RTestPath,
)
from radius_testing.domain import (
    TestRunPlan as RTestRunPlan,
)
from radius_testing.domain import (
    TestRunResult as RTestRunResult,
)
from radius_testing.domain import (
    TestRunStatus as RTestRunStatus,
)
from radius_testing.domain import (
    TestSelection as RTestSelection,
)
from radius_testing.domain import (
    TestSelectionReason as RTestSelectionReason,
)
from radius_testing.infrastructure import InMemoryTestStore, SqlAlchemyTestStore
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 19, tzinfo=UTC)


def _case(path: str) -> RTestCase:
    return RTestCase(
        id=uuid4(), name=RTestName(path.rsplit("/", 1)[-1]), path=RTestPath(path),
        framework=RTestFramework.PYTEST,
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _analysis(session: Session, org_name: str) -> db.Analysis:
    org = db.Organization(id=uuid4(), name=org_name)
    repo = db.Repository(
        id=uuid4(), organization_id=org.id, github_repository_id=len(org_name) * 1000 + ord(org_name[0]),
        name="app", owner=org_name.lower(), default_branch="main",
        clone_url=f"https://github.com/{org_name.lower()}/app.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    # SQLite does not enforce foreign keys here, so the pull request row can be omitted.
    analysis = db.Analysis(
        id=uuid4(), repository_id=repo.id, pull_request_id=uuid4(), commit_sha="a" * 40,
        status=AnalysisStatus.RUNNING, started_at=NOW, created_at=NOW,
    )
    session.add_all([org, repo, analysis])
    session.flush()
    return analysis


def test_selection_and_plan_never_include_other_tenants_test_cases(session) -> None:
    store = SqlAlchemyTestStore(session)
    ours = _analysis(session, "Acme")
    theirs = _analysis(session, "Globex")
    store.save_test_cases((_case("tests/test_secret_globex.py"),), theirs.repository_id)
    selected = _case("tests/test_pay.py")
    skipped = _case("tests/test_cart.py")
    store.save_test_cases((selected, skipped), ours.repository_id)
    store.save_selection(RTestSelection(
        analysis_id=ours.id,
        selected_tests=(SelectedTest(selected, RTestSelectionReason.AFFECTED_FILE),),
        skipped_tests=(skipped,),
    ))
    store.save_run_plan(RTestRunPlan.pending(
        ours.id, selected_tests=(selected,), command_plan=(("pytest", ("tests/test_pay.py",)),),
    ))

    selection = store.get_selection(ours.id)
    assert [t.path.value for t in selection.skipped_tests] == ["tests/test_cart.py"]
    assert selection.total_discovered_count == 2
    plan = store.get_run_plan(ours.id)
    assert [t.path.value for t in plan.selected_tests] == ["tests/test_pay.py"]


def _error_run(analysis_id) -> RTestRunResult:
    return RTestRunResult(
        id=uuid4(), analysis_id=analysis_id, status=RTestRunStatus.ERROR,
        total_tests=0, passed=0, failed=0, skipped=0, duration_ms=0,
    )


def test_error_run_reads_back_as_error_and_writes_no_passed_history(session) -> None:
    store = SqlAlchemyTestStore(session)
    analysis = _analysis(session, "Acme")
    case = _case("tests/test_pay.py")
    store.save_test_cases((case,), analysis.repository_id)
    store.save_selection(RTestSelection(
        analysis_id=analysis.id,
        selected_tests=(SelectedTest(case, RTestSelectionReason.AFFECTED_FILE),),
    ))

    store.save_run_result(_error_run(analysis.id))

    assert store.get_run_result(analysis.id).status is RTestRunStatus.ERROR
    history = session.scalars(select(db.TestExecutionHistory.status)).all()
    assert history == ["error"]


@pytest.mark.parametrize(
    ("passed", "failed", "total", "expected"),
    [(0, 0, 0, RTestRunStatus.ERROR), (2, 0, 2, RTestRunStatus.PASSED), (1, 1, 2, RTestRunStatus.FAILED)],
)
def test_rows_written_before_the_status_column_keep_a_safe_status(
    session, passed, failed, total, expected
) -> None:
    store = SqlAlchemyTestStore(session)
    analysis = _analysis(session, "Acme")
    session.add(db.TestRun(
        id=uuid4(), analysis_id=analysis.id, framework="mixed", total_tests=total,
        passed=passed, failed=failed, skipped=0, duration_ms=1, status=None,
    ))
    session.flush()
    assert store.get_run_result(analysis.id).status is expected


def test_in_memory_store_records_no_passed_history_for_an_error_run() -> None:
    store = InMemoryTestStore()
    analysis_id = uuid4()
    case = _case("tests/test_pay.py")
    store.save_selection(RTestSelection(
        analysis_id=analysis_id,
        selected_tests=(SelectedTest(case, RTestSelectionReason.AFFECTED_FILE),),
    ))
    store.save_run_result(_error_run(analysis_id))
    assert [row["status"] for row in store.get_test_history(analysis_id)] == ["error"]
