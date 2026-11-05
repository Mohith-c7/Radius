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


def test_same_test_path_in_two_repositories_is_stored_independently(tmp_path) -> None:
    from radius_testing.application import TestingApplicationService
    from radius_testing.dto import DiscoverTestsCommand
    from radius_testing.infrastructure import (
        ConventionalTestDiscoverer,
        PathBasedTestSelector,
        StaticTestCommandPlanner,
    )

    repo_a, repo_b = uuid4(), uuid4()
    for name, body in (("a", "def test_a():\n    pass\n"), ("b", "def test_b():\n    pass\n")):
        tests_dir = tmp_path / name / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_app.py").write_text(body, encoding="utf-8")

    with _session() as session:
        store = SqlAlchemyTestStore(session)
        service = TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=store,
            planner=StaticTestCommandPlanner(),
        )
        found_a = service.discover_test_cases(DiscoverTestsCommand(tmp_path / "a", repo_a))
        found_b = service.discover_test_cases(DiscoverTestsCommand(tmp_path / "b", repo_b))

        assert found_a[0].path.value == found_b[0].path.value == "tests/test_app.py"
        assert found_a[0].id != found_b[0].id
        assert [t.id for t in store.list_test_cases(repo_a)] == [found_a[0].id]
        assert [t.id for t in store.list_test_cases(repo_b)] == [found_b[0].id]
        assert len(store.list_test_cases()) == 2


def test_selection_totals_only_count_the_analysed_repository() -> None:
    """Another repository's tests are neither skipped nor counted for this run."""

    repo_a, repo_b, analysis_id = uuid4(), uuid4(), uuid4()

    def case(path: str) -> RadiusTestCase:
        return RadiusTestCase(
            id=uuid4(),
            name=RadiusTestName(path.rsplit("/", 1)[-1].removesuffix(".py")),
            path=RadiusTestPath(path),
            framework=RadiusTestFramework.PYTEST,
        )

    with _session() as session:
        store = SqlAlchemyTestStore(session)
        a_tests = store.save_test_cases(
            (case("tests/test_core.py"), case("tests/test_cli.py")), repo_a
        )
        store.save_test_cases(
            (case("tests/test_other.py"), case("tests/test_more.py"), case("tests/test_x.py")),
            repo_b,
        )
        store._analysis_repository_id = lambda _: repo_a  # analysis belongs to repo A
        selected = next(t for t in a_tests if t.path.value == "tests/test_core.py")
        store.save_selection(
            RadiusTestSelection(
                analysis_id=analysis_id,
                selected_tests=(SelectedTest(selected, RadiusTestSelectionReason.AFFECTED_FILE),),
            )
        )

        loaded = store.get_selection(analysis_id)

    assert loaded is not None
    assert [t.path.value for t in loaded.skipped_tests] == ["tests/test_cli.py"]
    assert loaded.total_discovered_count == 2
