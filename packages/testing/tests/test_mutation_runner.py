"""Mutation runners: local-runner refusal, sandbox command construction (fakes), orchestration."""

from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from radius_testing.infrastructure.sandbox_runner import (
    CONTAINER_JUNIT_PATH,
    SandboxConfig,
    build_container_argv,
    sandbox_command,
)
from radius_testing.mutation import (
    LocalRunnerRefusedError,
    MutationBudget,
    RunOutcome,
    SandboxMutantRunner,
    SubprocessLocalRunner,
    aggregate_criterion,
    generate_mutants,
    run_mutants,
)
from radius_testing.mutation.runner import (
    case_to_test_id,
    results_from_junit,
    validate_test_ids,
)

SRC = "def f(a, b):\n    if a > b:\n        return a - b\n    return 0\n"
T1, T2, T3 = "tests/test_f.py::test_a", "tests/test_f.py::test_b", "tests/test_f.py::test_c"


class FakeRunner:
    """Kills by a table: mutant description -> set of failing tests."""

    def __init__(self, table, *, flaky_baseline=(), flaky_survivor=None, timeout_for=None):
        self.table = table
        self.calls = 0
        self.flaky_baseline = set(flaky_baseline)
        self.flaky_survivor = flaky_survivor
        self.timeout_for = timeout_for
        self._base_n = 0
        self._seen: dict[str, int] = {}

    def run(self, mutant, tests, timeout, *, stop_on_first_failure=False):
        self.calls += 1
        res = {t: "passed" for t in tests}
        if mutant is None:
            self._base_n += 1
            if self._base_n == 1:
                for t in self.flaky_baseline:
                    res[t] = "failed"
            return RunOutcome("ok", res)
        if mutant.id == self.timeout_for:
            return RunOutcome("timeout")
        self._seen[mutant.id] = self._seen.get(mutant.id, 0) + 1
        for t in self.table.get(mutant.id, ()):
            res[t] = "failed"
        if mutant.id == self.flaky_survivor and self._seen[mutant.id] == 2:
            res[T1] = "failed"
        return RunOutcome("ok", res)


def _mutants():
    return generate_mutants(SRC, "src/f.py", operators=["ROR", "AOR"])


def test_local_runner_refused_without_opt_in(tmp_path: Path) -> None:
    with pytest.raises(LocalRunnerRefusedError):
        SubprocessLocalRunner(tmp_path, environ={})
    with pytest.raises(LocalRunnerRefusedError):
        SubprocessLocalRunner(tmp_path, environ={"RADIUS_MUTATION_ALLOW_LOCAL": "true"})


def test_validate_test_ids_blocks_option_and_path_injection() -> None:
    assert validate_test_ids(["tests/test_x.py::test_a[1-2]"]) == ["tests/test_x.py::test_a[1-2]"]
    for bad in ("--rootdir=/", "-x", "/etc/passwd", "../x.py::t", "C:\\x.py", "a;rm -rf /", ""):
        with pytest.raises(ValueError):
            validate_test_ids([bad])


def test_junit_case_id_mapping(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_f.py").write_text("")
    xml = (
        b'<testsuites><testsuite><testcase classname="tests.test_f" name="test_a"/>'
        b'<testcase classname="tests.test_f.TestC" name="test_b"><failure/></testcase>'
        b"</testsuite></testsuites>"
    )
    assert results_from_junit(xml, tmp_path) == {
        "tests/test_f.py::test_a": "passed",
        "tests/test_f.py::TestC::test_b": "failed",
    }
    assert case_to_test_id(SimpleNamespace(classname="zzz", name="t"), tmp_path) == "zzz::t"


def test_sandbox_adapter_command_construction_with_fakes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "f.py").write_text(SRC)
    cfg = SandboxConfig(timeout_seconds=30)
    seen = {}

    class FakeSandbox:
        config = cfg

        def run_collecting(self, plan, ws, artifacts=()):
            seen["plan"] = plan
            seen["artifacts"] = artifacts
            seen["written"] = (Path(ws) / "src" / "f.py").read_text()
            xml = (
                b'<testsuites><testsuite><testcase classname="tests.test_f" name="test_a">'
                b"<failure/></testcase></testsuite></testsuites>"
            )
            return SimpleNamespace(output=""), {"0/junit.xml": xml}

    runner = SandboxMutantRunner(repo, FakeSandbox())
    mutant = _mutants()[0]
    out = runner.run(mutant, [T1], 30, stop_on_first_failure=True)
    assert out.status == "ok" and out.results == {"tests.test_f::test_a": "failed"}
    (cmd, args), = seen["plan"].command_plan
    assert cmd == "python" and args == ("-m", "pytest", "-q", "-x", T1)
    assert seen["artifacts"] == ("junit.xml",)
    assert seen["written"] == mutant.mutated_source  # mutant lives only in the copy
    assert (repo / "src" / "f.py").read_text() == SRC  # the checkout is untouched

    # the planned command becomes a hardened container argv: no network, read-only, junit report
    inner, is_pytest = sandbox_command(cmd, args)
    argv = build_container_argv(
        cfg, runtime_path="docker", container_name="radius-sbx-abc",
        workspace_dir=tmp_path / "w", results_dir=tmp_path / "r", command=inner,
    )
    assert is_pytest and f"--junitxml={CONTAINER_JUNIT_PATH}" in argv
    joined = " ".join(argv)
    assert "--network none" in joined and "--read-only" in joined and "--pull never" in joined
    assert argv.index(cfg.image) < argv.index("pytest")
    with pytest.raises(ValueError):
        runner.build_plan(["--bad"])


def test_sandbox_adapter_timeout_and_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "f.py").write_text(SRC)

    def make(output):
        class S:
            config = SandboxConfig(timeout_seconds=5)

            def run_collecting(self, plan, ws, artifacts=()):
                return SimpleNamespace(output=output), {}

        return SandboxMutantRunner(repo, S())

    assert make("x timed out after 5 seconds").run(None, [T1], 5).status == "timeout"
    assert make("sandbox unavailable").run(None, [T1], 5).status == "error"


def test_run_mutants_builds_matrix_and_excludes_baseline_failures() -> None:
    ms = _mutants()
    table = {ms[0].id: {T1, T2}, ms[1].id: {T2}}
    runner = FakeRunner(table, flaky_baseline={T3})
    run = run_mutants(runner, ms, [T1, T2, T3], MutationBudget(), original_sources={"src/f.py": SRC})
    assert run.baseline_flaky == (T3,)
    assert run.matrix.tests == (T1, T2)
    by = {r.id: r for r in run.matrix.records}
    assert by[ms[0].id].status == "killed" and by[ms[0].id].killed_by == {T1, T2}
    assert by[ms[1].id].killed_by == {T2}
    assert all(by[m.id].status == "survived" for m in ms[2:])
    agg = aggregate_criterion(run.matrix, ["f"], [T1, T2], min_mutants=2)
    assert agg.killed_by_any == 2


def test_survivor_killed_on_rerun_is_flaky_and_timeouts_recorded() -> None:
    ms = _mutants()
    runner = FakeRunner({}, flaky_survivor=ms[0].id, timeout_for=ms[1].id)
    run = run_mutants(runner, ms, [T1, T2])
    by = {o.mutant_id: o.status for o in run.outcomes}
    assert by[ms[0].id] == "flaky" and by[ms[1].id] == "timeout"
    assert run.matrix.excluded()["flaky"] == [ms[0].id]


def test_wall_clock_budget_skips_remaining_and_cache_hits() -> None:
    ms = _mutants()
    ticks = iter(range(0, 1000, 10))
    runner = FakeRunner({})
    run = run_mutants(
        runner, ms, [T1], MutationBudget(wall_clock_seconds=15), clock=lambda: next(ticks)
    )
    assert run.skipped_for_budget and len(run.outcomes) + len(run.skipped_for_budget) == len(ms)

    cache: dict = {}
    r1 = FakeRunner({ms[0].id: {T1}})
    run_mutants(r1, ms, [T1], cache=cache)
    calls_cold = r1.calls
    r2 = FakeRunner({ms[0].id: {T1}})
    warm = run_mutants(r2, ms, [T1], cache=cache)
    assert warm.cache_hits == len(ms) and r2.calls == 2  # only the two baseline runs
    assert calls_cold > r2.calls
    # a different test set or image digest is a different cache entry
    r3 = FakeRunner({ms[0].id: {T1}})
    other = run_mutants(r3, ms, [T1], cache=cache, image_digest="sha256:other")
    assert other.cache_hits == 0


def test_baseline_failure_aborts() -> None:
    class Bad:
        def run(self, *a, **k):
            return RunOutcome("error", detail="no report")

    with pytest.raises(RuntimeError):
        run_mutants(Bad(), _mutants(), [T1])


def test_local_runner_end_to_end_on_a_tiny_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pytest.ini").write_text("[pytest]\npythonpath = src\n")
    (repo / "src" / "f.py").write_text(SRC)
    (repo / "tests" / "test_f.py").write_text(
        textwrap.dedent(
            """
            from f import f

            def test_a():
                assert f(3, 1) == 2

            def test_b():
                assert f(1, 3) == 0

            def test_c():
                assert f(2, 2) is not None
            """
        )
    )
    ms = generate_mutants(SRC, "src/f.py", scope=[(2, 3)], operators=["ROR", "AOR"])
    assert len(ms) == 2  # a > b -> a >= b ; a - b -> a + b
    env = {"RADIUS_MUTATION_ALLOW_LOCAL": "1"}
    before = (repo / "src" / "f.py").read_text()
    tests = ["tests/test_f.py::test_a", "tests/test_f.py::test_b", "tests/test_f.py::test_c"]
    with SubprocessLocalRunner(repo, environ=env) as runner:
        run = run_mutants(runner, ms, tests, MutationBudget(per_mutant_timeout_seconds=60),
                          baseline_runs=1, survivor_reruns=0)
    assert (repo / "src" / "f.py").read_text() == before
    by = {m.description: next(r for r in run.matrix.records if r.id == m.id) for m in ms}
    assert by["Sub->Add"].killed_by == {tests[0]}
    # a > b -> a >= b is behaviourally equivalent here (a - b == 0 when a == b): survives
    assert by["Gt->GtE"].status == "survived"


def test_dataclass_helper_used_nowhere_else() -> None:
    # guard: Mutant stays frozen so cache keys cannot drift
    m = _mutants()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.id = "x"  # type: ignore[misc]
