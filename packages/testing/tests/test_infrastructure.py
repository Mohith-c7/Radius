"""Testing infrastructure tests."""

from pathlib import Path
from uuid import uuid4

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
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)


def test_conventional_discoverer_finds_tests_and_ignores_vendor_dirs(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.test.ts").write_text("test('app', () => {})\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.test.ts").write_text("skip\n")

    tests = ConventionalTestDiscoverer().discover(tmp_path)

    assert [test.path.value for test in tests] == [
        "src/app.test.ts",
        "tests/test_app.py",
    ]
    assert tests[1].framework == RadiusTestFramework.PYTEST


def test_path_based_selector_selects_changed_and_conventional_tests() -> None:
    analysis_id = uuid4()
    tests = (
        _test("tests/test_app.py"),
        _test("src/service/test_core.py"),
        _test("src/app.test.ts", framework=RadiusTestFramework.UNKNOWN),
    )

    selection = PathBasedTestSelector().select(
        analysis_id,
        tests,
        changed_file_paths=("src/app.py", "src/service/core.py"),
    )

    assert [item.test_case.path.value for item in selection.selected_tests] == [
        "src/app.test.ts",
        "src/service/test_core.py",
        "tests/test_app.py",
    ]
    assert all(item.reason.value == "convention" for item in selection.selected_tests)


def test_static_planner_returns_structured_pytest_plan() -> None:
    analysis_id = uuid4()
    plan = StaticTestCommandPlanner().plan(
        analysis_id,
        (_test("tests/test_app.py"),),
    )

    assert plan.analysis_id == analysis_id
    assert plan.status.value == "pending"
    assert plan.command_plan == (("pytest", ("tests/test_app.py",)),)


def _test(
    path: str,
    framework: RadiusTestFramework = RadiusTestFramework.PYTEST,
) -> RadiusTestCase:
    return RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName(Path(path).stem),
        path=RadiusTestPath(path),
        framework=framework,
    )
