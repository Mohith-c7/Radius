"""SQLAlchemy testing store tests."""

from uuid import uuid4

from radius_shared.database.base import Base
from radius_testing.domain import (
    SelectedTest,
)
from radius_testing.domain import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain import (
    TestFramework as RadiusTestFramework,
)
from radius_testing.domain import (
    TestName as RadiusTestName,
)
from radius_testing.domain import (
    TestPath as RadiusTestPath,
)
from radius_testing.domain import (
    TestRunPlan as RadiusTestRunPlan,
)
from radius_testing.domain import (
    TestRunResult as RadiusTestRunResult,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.domain import (
    TestSelection as RadiusTestSelection,
)
from radius_testing.domain import (
    TestSelectionReason as RadiusTestSelectionReason,
)
from radius_testing.infrastructure import SqlAlchemyTestStore
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_test_store_persists_selection_plan_and_result() -> None:
    with _session() as session:
        store = SqlAlchemyTestStore(session)
        analysis_id = uuid4()
        test_case = RadiusTestCase(
            id=uuid4(),
            name=RadiusTestName("test_core"),
            path=RadiusTestPath("tests/test_core.py"),
            framework=RadiusTestFramework.PYTEST,
        )

        store.save_test_cases((test_case,))
        selection = store.save_selection(
            RadiusTestSelection(
                analysis_id=analysis_id,
                selected_tests=(
                    SelectedTest(test_case, RadiusTestSelectionReason.AFFECTED_FILE),
                ),
            )
        )
        plan = store.save_run_plan(
            RadiusTestRunPlan.pending(
                analysis_id,
                selected_tests=(test_case,),
                command_plan=(("python", ("-m", "pytest", "tests/test_core.py")),),
            )
        )
        result = store.save_run_result(
            RadiusTestRunResult(
                id=uuid4(),
                analysis_id=analysis_id,
                status=RadiusTestRunStatus.PASSED,
                total_tests=1,
                passed=1,
                failed=0,
                skipped=0,
                duration_ms=10,
            )
        )

        assert selection.selected_tests[0].test_case.path.value == "tests/test_core.py"
        assert store.get_selection(analysis_id).selected_tests[0].reason.value == (
            "affected_file"
        )
        assert store.get_run_plan(analysis_id).command_plan == plan.command_plan
        assert store.get_run_result(analysis_id).passed == result.passed


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
