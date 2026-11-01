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


def _plan(tmp_path: Path, command_plan, paths=("tests/test_ok.py",)):
    return RadiusTestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=tuple(
            RadiusTestCase(
                id=uuid4(),
                name=RadiusTestName(Path(p).stem),
                path=RadiusTestPath(p),
                framework=RadiusTestFramework.PYTEST,
            )
            for p in paths
        ),
        command_plan=command_plan,
    )


def test_runner_reports_real_per_test_counts_from_junit(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_mix.py").write_text(
        "import pytest\n"
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert True\n"
        "def test_c():\n    assert False\n"
        "@pytest.mark.skip\ndef test_d():\n    pass\n",
        encoding="utf-8",
    )
    import sys

    plan = _plan(
        tmp_path,
        ((sys.executable, ("-m", "pytest", "tests/test_mix.py")),),
        ("tests/test_mix.py",),
    )
    # The runner only enables JUnit output for the literal "python" command.
    plan = RadiusTestRunPlan.pending(
        analysis_id=plan.analysis_id,
        selected_tests=plan.selected_tests,
        command_plan=(("python", ("-m", "pytest", "tests/test_mix.py")),),
    )

    result = SubprocessTestRunner(timeout_seconds=60).run(plan, tmp_path)

    if result.status == RadiusTestRunStatus.ERROR:
        import pytest

        pytest.skip("pytest is not importable by the `python` on PATH")
    assert result.status == RadiusTestRunStatus.FAILED
    assert (result.total_tests, result.passed, result.failed, result.skipped) == (4, 2, 1, 1)


def test_missing_runner_binary_is_error_not_crash_or_pass(tmp_path: Path) -> None:
    plan = _plan(tmp_path, (("radius-no-such-binary", ("x.test.js",)),))

    result = SubprocessTestRunner(timeout_seconds=5).run(plan, tmp_path)

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "not found" in result.output


def test_timeout_is_error_not_failure_count(tmp_path: Path) -> None:
    import sys

    plan = _plan(tmp_path, ((sys.executable, ("-c", "import time; time.sleep(5)")),))

    result = SubprocessTestRunner(timeout_seconds=1).run(plan, tmp_path)

    assert result.status == RadiusTestRunStatus.ERROR
    assert result.passed == 0
    assert "timed out" in result.output


def test_no_tests_collected_contributes_zero_tests(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_empty.py").write_text("# nothing yet\n", encoding="utf-8")
    plan = _plan(
        tmp_path,
        (("python", ("-m", "pytest", "tests/test_empty.py")),),
        ("tests/test_empty.py",),
    )

    result = SubprocessTestRunner(timeout_seconds=60).run(plan, tmp_path)

    if result.status == RadiusTestRunStatus.ERROR:
        import pytest

        pytest.skip("pytest is not importable by the `python` on PATH")
    assert result.total_tests == 0
    assert result.failed == 0


def test_npx_missing_package_is_error_not_failure() -> None:
    outcome = SubprocessTestRunner._exit_code_outcome(
        "npx",
        1,
        'npm error npx canceled due to missing packages and no YES option: ["jest@30"]',
        ["a.test.js"],
    )

    assert outcome.error is not None
    assert outcome.failed == 0
