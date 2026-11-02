"""F-11 flaky-test handling: score, rerun classification, evidence, quarantine."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from radius_confidence.domain import AnalysisEvidence, ImpactEvidence, TestEvidence
from radius_confidence.infrastructure.scoring import DeterministicConfidenceScorer
from radius_testing.application import TestingApplicationService
from radius_testing.domain import (
    ExecutionSample,
    FlakinessConfig,
    RerunPolicy,
    RerunVerdict,
    SampleOutcome,
    classify_rerun,
    flakiness_score,
)
from radius_testing.domain import TestCase as RadiusTestCase
from radius_testing.domain import TestFramework as RadiusTestFramework
from radius_testing.domain import TestName as RadiusTestName
from radius_testing.domain import TestPath as RadiusTestPath
from radius_testing.domain import TestRunPlan as RadiusTestRunPlan
from radius_testing.domain import TestRunResult as RadiusTestRunResult
from radius_testing.domain import TestRunStatus as RadiusTestRunStatus
from radius_testing.infrastructure import ContainerSandboxRunner, SandboxConfig
from radius_testing.infrastructure.in_memory import InMemoryTestStore
from radius_testing.infrastructure.sqlalchemy_store import _history_status

P, F, X = SampleOutcome.PASSED, SampleOutcome.FAILED, SampleOutcome.FLAKY


def _samples(outcomes: str, code: str | None = "c1") -> tuple[ExecutionSample, ...]:
    table = {"P": P, "F": F, "X": X}
    return tuple(ExecutionSample(table[ch], code) for ch in outcomes)


# --------------------------------------------------------------------------
# Flakiness score (pure, seeded fixtures)
# --------------------------------------------------------------------------


def test_stable_pass_and_stable_fail_score_zero() -> None:
    assert flakiness_score(_samples("PPPPPP")).score == 0.0
    assert flakiness_score(_samples("FFFFFF")).score == 0.0
    assert not flakiness_score(_samples("FFFFFF")).quarantined


def test_alternating_results_on_same_code_are_flaky() -> None:
    result = flakiness_score(_samples("PFPFPF"))
    assert (result.comparable, result.flips, result.score) == (5, 5, 1.0)
    assert result.quarantined


def test_every_nth_run_failure_pattern_is_detected() -> None:
    # Seeded: fails on every 3rd run of the same commit.
    history = _samples("".join("F" if i % 3 == 0 else "P" for i in range(1, 19)))
    result = flakiness_score(history, FlakinessConfig(window=18))
    assert result.score is not None and result.score >= 0.5
    assert result.quarantined


def test_failure_fixed_by_a_code_change_is_not_a_flip() -> None:
    history = _samples("FFF", "old") + _samples("PPP", "new")
    result = flakiness_score(history)
    assert result.flips == 0
    assert result.score == 0.0


def test_cross_commit_history_without_shared_code_key_is_not_comparable() -> None:
    history = tuple(ExecutionSample(P if i % 2 else F, f"sha{i}") for i in range(10))
    assert flakiness_score(history).score is None
    unknown = tuple(ExecutionSample(P if i % 2 else F, None) for i in range(10))
    assert flakiness_score(unknown).score is None


def test_insufficient_history_never_quarantines() -> None:
    result = flakiness_score(_samples("PF"))
    assert result.score is None
    assert not result.quarantined
    assert not result.sufficient_history


def test_flaky_samples_count_as_flips() -> None:
    result = flakiness_score(_samples("XXXP"), FlakinessConfig(min_comparable=3))
    assert result.flips == 3 and result.quarantined


def test_window_limits_history_and_score_is_deterministic() -> None:
    history = _samples("PFPFPFPF" + "P" * 30)
    recent = flakiness_score(history, FlakinessConfig(window=10))
    assert recent.score == 0.0 and recent.samples_considered == 10
    wide = flakiness_score(history, FlakinessConfig(window=40))
    assert wide == flakiness_score(history, FlakinessConfig(window=40))
    assert wide.score is not None and wide.score > 0


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        FlakinessConfig(window=1)
    with pytest.raises(ValueError):
        FlakinessConfig(threshold=0)
    with pytest.raises(ValueError):
        RerunPolicy(reruns=-1)
    assert not RerunPolicy().enabled  # default: off


def test_classify_rerun() -> None:
    assert classify_rerun([False, False]) is RerunVerdict.STABLE_FAIL
    assert classify_rerun([False, True]) is RerunVerdict.FLAKY
    assert classify_rerun([]) is RerunVerdict.STABLE_FAIL


# --------------------------------------------------------------------------
# Rerun policy in the sandbox runner (fake container = local pytest)
# --------------------------------------------------------------------------

FLAKY_TEST = """
import os
from pathlib import Path

def test_flaky_every_second_run():
    counter = Path(os.environ["FLAKY_COUNTER"])
    runs = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(runs))
    assert runs % 2 == 0, f"seeded failure on run {runs}"
"""
STABLE_FAIL_TEST = "def test_always_fails():\n    assert False\n"
PASS_TEST = "def test_ok():\n    assert True\n"


class _Done:
    def __init__(self, code: int) -> None:
        self.code = code

    def wait(self, timeout=None) -> int:
        return self.code

    def kill(self) -> None:
        pass


class LocalPytestLauncher:
    """Stands in for ``docker run``: runs real pytest in the mounted workspace.

    The workspace is the runner's snapshot, so reruns see the same files; the
    flaky counter lives outside it (``FLAKY_COUNTER``) like real-world state.
    ``exit_codes`` overrides the exit code of the n-th launch (1-based).
    """

    def __init__(self, counter: Path, exit_codes: dict[int, int] | None = None) -> None:
        self.counter = counter
        self.exit_codes = exit_codes or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        mounts = {
            value.split("target=")[1].split(",")[0]: Path(value.split("source=")[1].split(",")[0])
            for flag, value in zip(argv, argv[1:], strict=False)
            if flag == "--mount"
        }
        self.calls.append(argv)
        index = len(self.calls)
        inner = argv[argv.index("python") :]
        inner = [
            f"--junitxml={mounts['/results'] / 'junit.xml'}" if a.startswith("--junitxml=") else a
            for a in inner
        ]
        inner[0] = sys.executable
        completed = subprocess.run(  # noqa: S603
            inner,
            cwd=mounts["/workspace"],
            env={
                **os.environ,
                "FLAKY_COUNTER": str(self.counter),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": "",
            },
            capture_output=True,
            check=False,
        )
        kwargs["stdout"].write(completed.stdout + completed.stderr)
        return _Done(self.exit_codes.get(index, completed.returncode))


class _Aux:
    def __call__(self, argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0)


def _plan(files: tuple[str, ...]) -> RadiusTestRunPlan:
    return RadiusTestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=tuple(
            RadiusTestCase(
                id=uuid4(),
                name=RadiusTestName(Path(f).stem),
                path=RadiusTestPath(f),
                framework=RadiusTestFramework.PYTEST,
            )
            for f in files
        ),
        command_plan=(("python", ("-m", "pytest", *files)),),
    )


def _run(tmp_path: Path, tests: dict[str, str], reruns: int, exit_codes=None):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    for name, body in tests.items():
        (repo / "tests" / name).write_text(body)
    launcher = LocalPytestLauncher(tmp_path / "counter.txt", exit_codes)
    runner = ContainerSandboxRunner(
        SandboxConfig(),
        launcher=launcher,
        aux_runner=_Aux(),
        which=lambda name: "/usr/bin/docker",
        probe=_Aux(),
        rerun_policy=RerunPolicy(reruns=reruns),
    )
    files = tuple(f"tests/{name}" for name in tests)
    return runner.run(_plan(files), repo), launcher


def test_rerun_disabled_by_default_keeps_failure(tmp_path: Path) -> None:
    result, launcher = _run(tmp_path, {"test_flaky.py": FLAKY_TEST}, reruns=0)
    # run 1 of the seeded every-2nd-run flake fails: no rerun, plain failure.
    assert result.status == RadiusTestRunStatus.FAILED
    assert (result.failed, result.flaky, result.flaky_tests) == (1, 0, ())
    assert len(launcher.calls) == 1


def test_flaky_test_is_detected_and_not_a_pass(tmp_path: Path) -> None:
    result, launcher = _run(tmp_path, {"test_flaky.py": FLAKY_TEST}, reruns=2)

    assert len(launcher.calls) == 2  # first run + one rerun that passed
    assert result.flaky == 1
    assert result.flaky_tests == ("tests/test_flaky.py::test_flaky_every_second_run",)
    assert result.failed == 0
    assert result.passed == 0  # never counted as a verified pass
    assert result.total_tests == 1
    assert result.status == RadiusTestRunStatus.PASSED
    assert "1 flaky, 0 stable_fail" in result.output


def test_stable_failure_stays_failed_after_all_reruns(tmp_path: Path) -> None:
    result, launcher = _run(tmp_path, {"test_bad.py": STABLE_FAIL_TEST}, reruns=2)

    assert len(launcher.calls) == 3
    assert (result.failed, result.flaky) == (1, 0)
    assert result.status == RadiusTestRunStatus.FAILED
    assert "0 flaky, 1 stable_fail" in result.output


def test_only_failing_files_are_rerun(tmp_path: Path) -> None:
    result, launcher = _run(
        tmp_path, {"test_flaky.py": FLAKY_TEST, "test_ok.py": PASS_TEST}, reruns=1
    )
    rerun_argv = launcher.calls[1]
    assert "tests/test_flaky.py" in rerun_argv
    assert "tests/test_ok.py" not in rerun_argv
    assert (result.passed, result.flaky, result.failed) == (1, 1, 0)


def test_mixed_flaky_and_stable_failure_still_fails(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path, {"test_flaky.py": FLAKY_TEST, "test_bad.py": STABLE_FAIL_TEST}, reruns=2
    )
    assert result.status == RadiusTestRunStatus.FAILED
    assert (result.failed, result.flaky) == (1, 1)


@pytest.mark.parametrize("code", [137, 152, 153])
def test_sandbox_error_during_rerun_is_not_flakiness(tmp_path: Path, code: int) -> None:
    result, launcher = _run(
        tmp_path, {"test_flaky.py": FLAKY_TEST}, reruns=3, exit_codes={2: code}
    )
    assert len(launcher.calls) == 2  # aborted at the errored rerun
    assert (result.failed, result.flaky) == (1, 0)
    assert result.status == RadiusTestRunStatus.FAILED
    assert "aborted" in result.output


@pytest.mark.parametrize("code", [137, 152, 153])
def test_sandbox_error_on_first_run_is_error_and_not_rerun(tmp_path: Path, code: int) -> None:
    result, launcher = _run(
        tmp_path, {"test_flaky.py": FLAKY_TEST}, reruns=3, exit_codes={1: code}
    )
    assert result.status == RadiusTestRunStatus.ERROR
    assert len(launcher.calls) == 1
    assert result.flaky == 0


def test_rerun_outcomes_are_deterministic(tmp_path: Path) -> None:
    runs = []
    for index in range(3):
        sub = tmp_path / f"r{index}"
        sub.mkdir()
        result, _ = _run(sub, {"test_flaky.py": FLAKY_TEST, "test_ok.py": PASS_TEST}, reruns=2)
        runs.append(
            (
                result.status,
                result.total_tests,
                result.passed,
                result.failed,
                result.flaky,
                result.flaky_tests,
            )
        )
    assert runs[0] == runs[1] == runs[2]


# --------------------------------------------------------------------------
# Evidence: flaky is never strong evidence
# --------------------------------------------------------------------------

IMPACT = ImpactEvidence(
    affected_files=1, affected_symbols=1, affected_modules=1, affected_tests=1, dependency_depth=1
)
ANALYSIS = AnalysisEvidence(changed_files=1, covered_files=("src/a.py",))


def _verdict(tests: TestEvidence) -> tuple[str, list]:
    result = DeterministicConfidenceScorer().score(IMPACT, tests, ANALYSIS)
    return result.metrics["verification_status"], list(result[1])


def _evidence(**kwargs) -> TestEvidence:
    base = {"total_tests": 1, "passed": 0, "failed": 0, "skipped": 0, "selected_test_files": 1}
    return TestEvidence(**{**base, **kwargs})


def test_flaky_only_run_is_not_verified() -> None:
    assert _verdict(_evidence(passed=1))[0] == "verified"
    status, evidence = _verdict(_evidence(flaky=1, flaky_tests=("tests/test_x.py::test_x",)))
    assert status == "insufficient_evidence"
    assert any(item.label == "flaky_test" for item in evidence)
    assert not any(item.label == "passed" for item in evidence)


def test_flaky_alongside_passes_blocks_verified_but_stable_fail_still_fails() -> None:
    mixed = _evidence(total_tests=3, passed=2, flaky=1, flaky_tests=("a::b",))
    assert _verdict(mixed)[0] == "insufficient_evidence"
    failing = _evidence(total_tests=3, passed=1, failed=1, flaky=1, flaky_tests=("a::b",))
    assert _verdict(failing)[0] == "failed"


def test_evidence_without_flaky_is_unchanged_and_deterministic() -> None:
    first = DeterministicConfidenceScorer().score(IMPACT, _evidence(passed=1), ANALYSIS)
    second = DeterministicConfidenceScorer().score(IMPACT, _evidence(passed=1), ANALYSIS)
    assert first == second
    assert _evidence(passed=1).flaky == 0
    assert not any(item.label == "flaky_test" for item in first[1])


# --------------------------------------------------------------------------
# Quarantine listing from history
# --------------------------------------------------------------------------


class _Store(InMemoryTestStore):
    def __init__(self, rows: list[dict]) -> None:
        super().__init__()
        self._rows = rows

    def list_test_samples(self, repository_id, limit: int = 5000):
        return self._rows[-limit:]


def _row(path: str, status: str, sha: str = "a" * 40) -> dict:
    return {"test_path": path, "test_name": Path(path).stem, "status": status, "commit_sha": sha}


def _service(rows: list[dict]) -> TestingApplicationService:
    return TestingApplicationService(None, None, _Store(rows), None)  # type: ignore[arg-type]


def test_quarantine_listing_is_scored_sorted_and_deterministic() -> None:
    rows = (
        [_row("tests/test_stable.py", "passed") for _ in range(8)]
        + [_row("tests/test_bad.py", "failed") for _ in range(8)]
        + [_row("tests/test_flip.py", "passed" if i % 2 else "failed") for i in range(8)]
        + [_row("tests/test_rerun.py", "flaky") for _ in range(4)]
        + [_row("tests/test_new.py", "failed")]
    )
    first = _service(rows).list_flaky_tests(uuid4())
    second = _service(rows).list_flaky_tests(uuid4())

    assert [t.test_path for t in first.quarantined] == [
        "tests/test_flip.py",
        "tests/test_rerun.py",
    ]
    assert first.insufficient_history_count == 1
    assert first.quarantined == second.quarantined
    assert all(t.score is not None and t.score >= first.threshold for t in first.quarantined)


def test_history_status_flaky_is_recorded_only_without_stable_failures() -> None:
    def result(failed: int) -> RadiusTestRunResult:
        return RadiusTestRunResult(
            id=uuid4(),
            analysis_id=uuid4(),
            status=RadiusTestRunStatus.PASSED,
            total_tests=2,
            passed=1,
            failed=failed,
            skipped=0,
            duration_ms=1,
            flaky=1,
            flaky_tests=("tests/test_a.py::t",),
        )

    assert _history_status(result(0), "tests/test_a.py", {"tests/test_a.py"}) == "flaky"
    assert _history_status(result(0), "tests/test_b.py", {"tests/test_a.py"}) == "passed"
    assert _history_status(result(1), "tests/test_a.py", {"tests/test_a.py"}) == "failed"


# --------------------------------------------------------------------------
# Real container (skipped without docker + the sandbox test image)
# --------------------------------------------------------------------------

_IMAGE = os.environ.get("RADIUS_SANDBOX_TEST_IMAGE", "radius-sandbox-test:latest")


def _docker_ready() -> bool:
    import shutil

    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        done = subprocess.run(  # noqa: S603
            [docker, "image", "inspect", _IMAGE], capture_output=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker or sandbox test image unavailable")
def test_real_container_reruns_stable_failure_and_keeps_it_failed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_bad.py").write_text(STABLE_FAIL_TEST)
    (repo / "tests" / "test_ok.py").write_text(PASS_TEST)
    runner = ContainerSandboxRunner(
        SandboxConfig(image=_IMAGE, timeout_seconds=120), rerun_policy=RerunPolicy(reruns=1)
    )

    result = runner.run(_plan(("tests/test_bad.py", "tests/test_ok.py")), repo)

    assert result.status == RadiusTestRunStatus.FAILED, result.output
    assert (result.passed, result.failed, result.flaky) == (1, 1, 0)
    assert "1 rerun(s) completed, 0 flaky, 1 stable_fail" in result.output
