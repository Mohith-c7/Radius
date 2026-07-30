"""Subprocess test runner tests."""

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
from radius_testing.domain import (
    TestRunPlan as RadiusTestRunPlan,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.infrastructure import SubprocessTestRunner


def test_subprocess_runner_executes_pytest_plan(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    test_case = RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName("test_ok"),
        path=RadiusTestPath("tests/test_ok.py"),
        framework=RadiusTestFramework.PYTEST,
    )
    plan = RadiusTestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=(test_case,),
        command_plan=(("python", ("-m", "pytest", "tests/test_ok.py")),),
    )

    result = SubprocessTestRunner(timeout_seconds=30).run(plan, tmp_path)

    assert result.status == RadiusTestRunStatus.PASSED
    assert result.passed == 1
    assert result.failed == 0
