"""measure_mutation: budgets, degradation ladder, caching, flakiness, equivalence, safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from radius_testing.mutation import (
    LocalRunnerRefusedError,
    MeasureConfig,
    MutantOutcome,
    MutationBudget,
    RunOutcome,
    SubprocessLocalRunner,
    SymbolTarget,
    collapse_results,
    context_hash,
    is_test_path,
    measure_mutation,
)

SRC = "def f(a, b):\n    if a > b:\n        return a - b\n    return 0\n"
T1, T2 = "tests/test_f.py::test_a", "tests/test_f.py::test_b"
IMAGE = "sha256:" + "a" * 64


class FakeRunner:
    """Kills by a table ``{operator: {failing tests}}``; records every call."""

    def __init__(
        self,
        table: dict[str, set[str]] | None = None,
        *,
        flaky_baseline: set[str] = frozenset(),
        failing_baseline: set[str] = frozenset(),
        timeout_ops: set[str] = frozenset(),
        flaky_survivor_ops: set[str] = frozenset(),
        control_fails: bool = False,
        baseline_status: str = "ok",
        duration: float = 0.1,
        raise_on_run: bool = False,
    ) -> None:
        self.table = table or {}
        self.flaky_baseline = set(flaky_baseline)
        self.failing_baseline = set(failing_baseline)
        self.timeout_ops = set(timeout_ops)
        self.flaky_survivor_ops = set(flaky_survivor_ops)
        self.control_fails = control_fails
        self.baseline_status = baseline_status
        self.duration = duration
        self.raise_on_run = raise_on_run
        self.calls: list[tuple[str | None, tuple[str, ...]]] = []
        self._base = 0
        self._seen: dict[str, int] = {}

    def run(self, mutant, tests, timeout, *, stop_on_first_failure=False):
        if self.raise_on_run:
            raise RuntimeError("boom")
        assert not stop_on_first_failure  # per-test attribution needs every failing test
        op = None if mutant is None else mutant.operator
        self.calls.append((op, tuple(tests)))
        res = {t: "passed" for t in tests}
        if mutant is None:
            self._base += 1
            if self.baseline_status != "ok":
                return RunOutcome(self.baseline_status, {}, self.duration, "x")
            for t in self.failing_baseline & set(tests):
                res[t] = "failed"
            if self._base == 1:
                for t in self.flaky_baseline & set(tests):
                    res[t] = "failed"
            return RunOutcome("ok", res, self.duration)
        if op == "CONTROL":
            if self.control_fails:
                res[tests[0]] = "failed"
            return RunOutcome("ok", res, self.duration)
        if op in self.timeout_ops:
            return RunOutcome("timeout", {}, self.duration, "timeout")
        n = self._seen[mutant.id] = self._seen.get(mutant.id, 0) + 1
        for t in self.table.get(op, set()) & set(tests):
            res[t] = "failed"
        if op in self.flaky_survivor_ops and n == 2:
            res[tests[0]] = "failed"
        return RunOutcome("ok", res, self.duration)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "f.py").write_text(SRC)
    (tmp_path / "tests" / "test_f.py").write_text("def test_a(): pass\n")
    return tmp_path


def target(tests=(T1, T2), path="src/f.py", symbol="python:src/f.py::f#function@1") -> SymbolTarget:
    return SymbolTarget(symbol, path, ((1, 4),), tuple(tests))


def cfg(**kw) -> MeasureConfig:
    budget = kw.pop("budget", MutationBudget(max_mutants=50, wall_clock_seconds=600))
    return MeasureConfig(budget=budget, **kw)


def by_op(m):
    return {r.operator: r for r in m.mutants}


def test_kill_matrix_statuses_and_attribution(repo: Path) -> None:
    runner = FakeRunner({"ROR": {T1}, "AOR": {T1, T2}, "RET": {T2}, "NEG": {T1}, "CRM": {T1}})
    m = measure_mutation(runner, repo, [target()], cfg())
    assert m.status == "measured" and m.generated == 7 and m.sampled == 7
    recs = {(r.operator, r.line): r for r in m.mutants}
    assert recs[("AOR", 3)].killed_by == (T1, T2)
    assert recs[("ROR", 2)].killed_by == (T1,)
    assert recs[("CON", 4)].status == "survived" and recs[("CON", 4)].killed_by == ()
    assert m.symbol_tests["python:src/f.py::f#function@1"] == (T1, T2)
    # a stable linked test is run for each mutant; control run happens once per file
    assert [c[0] for c in runner.calls].count("CONTROL") == 1


def test_never_uses_early_exit_and_runs_only_linked_tests(repo: Path) -> None:
    other = target(tests=("tests/test_f.py::test_other",), symbol="python:src/g.py::g#function@1")
    runner = FakeRunner({})
    measure_mutation(runner, repo, [target(), other], cfg())
    mutant_calls = [c for c in runner.calls if c[0] not in (None, "CONTROL")]
    assert all(set(tests) <= {T1, T2, "tests/test_f.py::test_other"} for _, tests in mutant_calls)


def test_failing_and_flaky_baseline_tests_are_excluded_and_listed(repo: Path) -> None:
    runner = FakeRunner({"ROR": {T1}}, flaky_baseline={T2})
    m = measure_mutation(runner, repo, [target()], cfg())
    assert m.baseline_flaky == (T2,)
    assert m.symbol_tests["python:src/f.py::f#function@1"] == (T1,)
    runner = FakeRunner({}, failing_baseline={T1, T2})
    m = measure_mutation(runner, repo, [target()], cfg())
    assert m.status == "unmeasured" and m.reason == "no_stable_linked_tests"
    assert set(m.baseline_failed) == {T1, T2}


def test_baseline_run_twice_by_default(repo: Path) -> None:
    runner = FakeRunner({})
    measure_mutation(runner, repo, [target()], cfg())
    assert sum(1 for c in runner.calls if c[0] is None) == 2


def test_baseline_error_degrades_never_raises(repo: Path) -> None:
    for status in ("error", "timeout"):
        m = measure_mutation(FakeRunner(baseline_status=status), repo, [target()], cfg())
        assert (m.status, m.reason) == ("unmeasured", "baseline_failed_to_run")
    m = measure_mutation(FakeRunner(raise_on_run=True), repo, [target()], cfg())
    assert m.status == "unmeasured" and m.reason == "measurement_failed:RuntimeError"


def test_survivor_rerun_killed_is_flaky_and_excluded(repo: Path) -> None:
    runner = FakeRunner({"ROR": {T1}}, flaky_survivor_ops={"CON"})
    m = measure_mutation(runner, repo, [target()], cfg())
    assert by_op(m)["CON"].status == "flaky"
    assert by_op(m)["AOR"].status == "survived"


def test_timeouts_rerun_once_then_excluded(repo: Path) -> None:
    runner = FakeRunner({"ROR": {T1}}, timeout_ops={"CON"})
    m = measure_mutation(runner, repo, [target()], cfg())
    assert by_op(m)["CON"].status == "timeout"
    assert [c[0] for c in runner.calls].count("CON") == 2


def test_equivalent_suspects_are_listed_not_run_not_counted(repo: Path) -> None:
    src = "def g(x):\n    y = x + 0\n    return y * 2\n"
    (repo / "src" / "g.py").write_text(src)
    t = SymbolTarget("python:src/g.py::g#function@1", "src/g.py", ((1, 3),), (T1,))
    runner = FakeRunner({"AOR": {T1}, "RET": {T1}, "CON": {T1}, "NEG": {T1}})
    m = measure_mutation(runner, repo, [t], cfg(min_decided=1))
    suspects = [r for r in m.mutants if r.equivalent_suspect]
    assert suspects and all(r.status == "equivalent_suspect" for r in suspects)
    assert all(r.killed_by == () for r in suspects)
    # suspect mutants never reach the runner: the number of mutant runs equals the others
    runs = [c for c in runner.calls if c[0] not in (None, "CONTROL")]
    assert len(runs) == len([r for r in m.mutants if not r.equivalent_suspect])


def test_sampling_is_seeded_and_deterministic(repo: Path) -> None:
    small = cfg(budget=MutationBudget(max_mutants=5, wall_clock_seconds=600, seed=7), min_decided=1)
    a = measure_mutation(FakeRunner(), repo, [target()], small)
    b = measure_mutation(FakeRunner(), repo, [target()], small)
    assert [r.mutant_id for r in a.mutants] == [r.mutant_id for r in b.mutants]
    assert a.sampled == 5 and a.generated == 7 and "sampled:5of7" in a.ladder


def test_budget_ladder_cuts_then_gives_up(repo: Path) -> None:
    clock_now = [0.0]

    def clock() -> float:
        return clock_now[0]

    # each run "takes" 10 s of the 60 s budget: 6 runs fit, mutants + controls + reruns do not
    runner = FakeRunner({"ROR": {T1}}, duration=10.0)
    m = measure_mutation(
        runner, repo, [target()],
        cfg(budget=MutationBudget(max_mutants=50, wall_clock_seconds=60), min_decided=1),
        clock=clock,
    )
    assert any(x.startswith(("tier_a_only", "budget_cut")) for x in m.ladder)
    # a budget that cannot fit the minimum sample ends in "unmeasured, static cap"
    runner = FakeRunner({}, duration=50.0)
    m = measure_mutation(
        runner, repo, [target()],
        cfg(budget=MutationBudget(max_mutants=50, wall_clock_seconds=60), min_decided=5),
        clock=clock,
    )
    assert m.status == "unmeasured" and m.reason == "budget_insufficient"


def test_wall_clock_expiry_marks_remaining_as_skipped(repo: Path) -> None:
    now = [0.0]

    class TickingRunner(FakeRunner):
        def run(self, mutant, tests, timeout, **kw):
            out = super().run(mutant, tests, timeout, **kw)
            if mutant is not None and mutant.operator != "CONTROL":
                now[0] += 100.0  # the wall clock jumps while mutants run
            return out

    m = measure_mutation(
        TickingRunner(), repo, [target()],
        cfg(budget=MutationBudget(max_mutants=50, wall_clock_seconds=250), min_decided=1),
        clock=lambda: now[0],
    )
    assert m.skipped_for_budget > 0
    assert any(r.status == "skipped_for_budget" for r in m.mutants)
    assert any(x.startswith("wall_clock_expired") for x in m.ladder)


def test_too_few_decided_mutants_is_unmeasured(repo: Path) -> None:
    m = measure_mutation(FakeRunner(), repo, [target()], cfg(min_decided=50))
    assert m.status == "unmeasured" and m.reason == "too_few_decided_mutants"
    assert m.mutants  # listed for transparency


def test_control_failure_excludes_the_file(repo: Path) -> None:
    m = measure_mutation(FakeRunner(control_fails=True), repo, [target()], cfg())
    assert any(x.startswith("control_failed:src/f.py") for x in m.ladder)
    assert m.status == "unmeasured"


def test_cache_hit_miss_and_disabled_without_image_digest(repo: Path) -> None:
    cache: dict[str, MutantOutcome] = {}
    r1 = FakeRunner({"ROR": {T1}})
    m1 = measure_mutation(r1, repo, [target()], cfg(), cache=cache, image_digest=IMAGE)
    assert m1.cache_hits == 0 and cache  # final statuses stored
    assert all(v.status in {"killed", "survived"} for v in cache.values())
    r2 = FakeRunner({"ROR": {T1}})
    m2 = measure_mutation(r2, repo, [target()], cfg(), cache=cache, image_digest=IMAGE)
    assert m2.cache_hits == 7
    assert [c for c in r2.calls if c[0] not in (None, "CONTROL")] == []
    assert [(r.mutant_id, r.status, r.killed_by) for r in m1.mutants] == [
        (r.mutant_id, r.status, r.killed_by) for r in m2.mutants
    ]
    # another image digest: miss
    r3 = FakeRunner({"ROR": {T1}})
    m3 = measure_mutation(r3, repo, [target()], cfg(), cache=cache, image_digest="sha256:" + "b" * 64)
    assert m3.cache_hits == 0
    # an edited test body (same ids) changes the repository context hash: miss
    (repo / "tests" / "test_f.py").write_text("def test_a(): assert 1\n")
    m4 = measure_mutation(FakeRunner(), repo, [target()], cfg(), cache=cache, image_digest=IMAGE)
    assert m4.cache_hits == 0
    # unknown image identity: the cache is not used at all (never guess)
    cache2: dict[str, MutantOutcome] = {}
    measure_mutation(FakeRunner(), repo, [target()], cfg(), cache=cache2, image_digest="")
    assert cache2 == {}


def test_non_final_results_are_never_cached(repo: Path) -> None:
    cache: dict[str, MutantOutcome] = {}
    runner = FakeRunner({}, timeout_ops={"CON"}, flaky_survivor_ops={"RET"})
    m = measure_mutation(runner, repo, [target()], cfg(), cache=cache, image_digest=IMAGE)
    statuses = {r.status for r in m.mutants}
    assert {"timeout", "flaky"} <= statuses
    assert {v.status for v in cache.values()} <= {"killed", "survived"}
    assert len(cache) == len([r for r in m.mutants if r.status in {"killed", "survived"}])


def test_test_files_are_never_mutated_and_unsafe_ids_dropped(repo: Path) -> None:
    (repo / "tests" / "helpers.py").write_text(SRC)
    bad = SymbolTarget("s", "tests/helpers.py", ((1, 4),), (T1,))
    conftest = SymbolTarget("c", "conftest.py", ((1, 4),), (T1,))
    m = measure_mutation(FakeRunner(), repo, [bad, conftest], cfg())
    assert (m.status, m.reason) == ("unmeasured", "no_mutable_symbols_with_tests")
    unsafe = SymbolTarget("python:src/f.py::f#function@1", "src/f.py", ((1, 4),), ("--co", "../x::t", T1))
    runner = FakeRunner()
    m = measure_mutation(runner, repo, [unsafe], cfg())
    assert any(x.startswith("unsafe_test_ids_dropped:2") for x in m.ladder)
    assert all(t == T1 for _, tests in runner.calls for t in tests)
    assert is_test_path("pkg/tests/util.py") and is_test_path("test_x.py") and not is_test_path("src/f.py")


def test_path_escape_and_missing_source_are_ignored(repo: Path) -> None:
    escape = SymbolTarget("e", "../outside.py", ((1, 4),), (T1,))
    missing = SymbolTarget("m", "src/missing.py", ((1, 4),), (T1,))
    m = measure_mutation(FakeRunner(), repo, [escape, missing], cfg())
    assert m.status == "unmeasured"


def test_local_runner_refused_unless_explicitly_allowed(repo: Path) -> None:
    with SubprocessLocalRunner(repo, environ={"RADIUS_MUTATION_ALLOW_LOCAL": "1"}) as local:
        with pytest.raises(LocalRunnerRefusedError):
            measure_mutation(local, repo, [target()], cfg())


def test_the_checkout_is_never_written_by_the_orchestration(repo: Path) -> None:
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    measure_mutation(FakeRunner({"ROR": {T1}}), repo, [target()], cfg())
    assert before == {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}


def test_collapse_results_parametrised_missing_and_precedence() -> None:
    res = {
        "t.py::a[1]": "passed", "t.py::a[2]": "failed", "t.py::b": "passed",
        "t.py::c[x]": "skipped", "t.py::c[y]": "passed",
    }
    out = collapse_results(res, ["t.py::a", "t.py::b", "t.py::c", "t.py::d", "t.py::ab"])
    assert out == {
        "t.py::a": "failed", "t.py::b": "passed", "t.py::c": "skipped", "t.py::d": None,
        "t.py::ab": None,
    }


def test_context_hash_changes_with_any_covered_file(repo: Path) -> None:
    h1 = context_hash(repo)
    assert h1 == context_hash(repo)
    (repo / "src" / "helper.py").write_text("X = 1\n")
    h2 = context_hash(repo)
    (repo / "src" / "helper.py").write_text("X = 2\n")
    assert len({h1, h2, context_hash(repo)}) == 3


@pytest.mark.parametrize("name", ["data.csv", "q.sql", "fixture.xml", "NOTES.md", "blob.bin", "uv.lock"])
def test_b14_context_hash_covers_data_and_binary_files_not_only_code(repo: Path, name: str) -> None:
    before = context_hash(repo)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / name).write_bytes(b"1\n")
    added = context_hash(repo)
    (repo / "tests" / name).write_bytes(b"2\x00\n")
    changed = context_hash(repo)
    assert len({before, added, changed}) == 3


def test_b14_tool_directories_do_not_change_the_hash(repo: Path) -> None:
    before = context_hash(repo)
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "x").write_text("1")
    assert context_hash(repo) == before
