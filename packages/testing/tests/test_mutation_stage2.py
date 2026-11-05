"""Mutation stage 2 (DEC-036): wider test set for stage-1 survivors, link-gap evidence.

Fake runner only: nothing is executed. Covers the stage-2 budget (max tests, wall clock),
early exit, the confirmation run, caching (stage-1 keys stay valid), exclusion of linked
and baseline-failing tests, and that nothing changes when stage 2 is off.
"""

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
    discover_wide_test_files,
    measure_mutation,
)

SRC = "def f(a, b):\n    if a > b:\n        return a - b\n    return 0\n"
SYM = "python:src/f.py::f#function@1"
T1, T2 = "tests/test_f.py::test_a", "tests/test_f.py::test_b"
W1, W2, W3 = (f"tests/test_wide.py::test_w{i}" for i in (1, 2, 3))
IMAGE = "sha256:" + "a" * 64
WIDE_FILE = "tests/test_wide.py"


class Stage2Runner:
    """Fake runner: stage 1 table ``{operator: failing linked tests}``, stage 2 table
    ``{operator: failing wide tests}``. ``-x`` runs report only the first failure (sorted)."""

    def __init__(
        self,
        stage1: dict[str, set[str]] | None = None,
        stage2: dict[str, set[str]] | None = None,
        *,
        wide_tests: tuple[str, ...] = (W1, W2, W3),
        wide_failing_baseline: frozenset[str] = frozenset(),
        flaky_kill: frozenset[str] = frozenset(),  # kill only on the first stage-2 run
        error_ops: frozenset[str] = frozenset(),
        advance: float = 0.0,
    ) -> None:
        self.stage1 = stage1 or {}
        self.stage2 = stage2 or {}
        self.wide_tests = wide_tests
        self.wide_failing_baseline = wide_failing_baseline
        self.flaky_kill = set(flaky_kill)
        self.error_ops = set(error_ops)
        self.advance = advance
        self.t = 0.0
        self.calls: list[tuple[str | None, tuple[str, ...], bool]] = []
        self._wide_runs: dict[str, int] = {}

    def clock(self) -> float:
        return self.t

    def _expand(self, tests):
        out = []
        for t in tests:
            if t == WIDE_FILE:
                out.extend(self.wide_tests)
            elif t == "tests/test_f.py":
                out.extend([T1, T2])  # the linked tests live in this file too
            else:
                out.append(t)
        return out

    def run(self, mutant, tests, timeout, *, stop_on_first_failure=False):
        self.t += self.advance
        op = None if mutant is None else mutant.operator
        self.calls.append((op, tuple(tests), stop_on_first_failure))
        ids = self._expand(tests)
        res = {t: "passed" for t in ids}
        if mutant is None:
            for t in self.wide_failing_baseline & set(ids):
                res[t] = "failed"
            return RunOutcome("ok", res, 0.1)
        if op == "CONTROL":
            return RunOutcome("ok", res, 0.1)
        is_wide = any(t in self.wide_tests for t in ids)
        if is_wide:
            if op in self.error_ops:
                return RunOutcome("error", {}, 0.1, "boom")
            n = self._wide_runs[mutant.id] = self._wide_runs.get(mutant.id, 0) + 1
            fails = sorted(self.stage2.get(op, set()) & set(ids))
            if op in self.flaky_kill and n > 1:
                fails = []
            if stop_on_first_failure:
                fails = fails[:1]  # early exit: pytest -x stops at the first failure
            for t in fails:
                res[t] = "failed"
            return RunOutcome("ok", res, 0.1)
        for t in self.stage1.get(op, set()) & set(ids):
            res[t] = "failed"
        return RunOutcome("ok", res, 0.1)

    def wide_mutant_calls(self):
        return [c for c in self.calls if c[0] not in (None, "CONTROL") and set(c[1]) & {WIDE_FILE, *self.wide_tests}]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "f.py").write_text(SRC)
    (tmp_path / "tests" / "test_f.py").write_text("from src.f import f\ndef test_a(): pass\n")
    (tmp_path / "tests" / "test_wide.py").write_text(
        "from f import f\ndef test_w1(): pass\ndef test_w2(): pass\ndef test_w3(): pass\n"
    )
    (tmp_path / "tests" / "test_unrelated.py").write_text("import os\ndef test_u(): pass\n")
    return tmp_path


def target() -> SymbolTarget:
    return SymbolTarget(SYM, "src/f.py", ((1, 4),), (T1, T2))


def cfg(**kw) -> MeasureConfig:
    return MeasureConfig(budget=MutationBudget(max_mutants=50, wall_clock_seconds=600), **kw)


def recs(m):
    return {r.operator: r for r in m.mutants}


KILL_STAGE1 = {"ROR": {T1}, "AOR": {T1}, "RET": {T2}, "NEG": {T1}, "CRM": {T1}}  # CON survives


def test_discovery_is_static_sorted_and_only_returns_importing_test_files(repo: Path) -> None:
    found = discover_wide_test_files(repo, ["src/f.py"], max_files=10)
    assert found == {"src/f.py": ("tests/test_f.py", "tests/test_wide.py")}
    assert discover_wide_test_files(repo, ["src/f.py"], max_files=1)["src/f.py"] == ("tests/test_f.py",)


def test_stage2_off_adds_no_runs_and_no_fields(repo: Path) -> None:
    off = Stage2Runner(KILL_STAGE1, {"CON": {W2}})
    m = measure_mutation(off, repo, [target()], cfg())
    assert m.stage2 is None and all(r.killed_outside_linked is None for r in m.mutants)
    assert off.wide_mutant_calls() == [] and all(not c[2] for c in off.calls)
    on = Stage2Runner(KILL_STAGE1, {"CON": {W2}})
    m2 = measure_mutation(on, repo, [target()], cfg(stage2=True))
    # stage 1 content is identical with stage 2 on; only killed_outside_linked is added
    strip = lambda mm: [(r.mutant_id, r.status, r.killed_by) for r in mm.mutants]  # noqa: E731
    assert strip(m) == strip(m2)


def test_survivor_killed_by_unlinked_test_is_recorded_and_stays_a_stage1_survivor(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W2, W3}})
    m = measure_mutation(runner, repo, [target()], cfg(stage2=True))
    con = recs(m)["CON"]
    assert con.status == "survived" and con.killed_by == ()  # stage 1 result untouched
    assert con.killed_outside_linked == (W2,)  # early exit: only the first killer (sorted)
    assert all(r.killed_outside_linked is None for r in m.mutants if r.status == "killed")
    s = m.stage2
    assert (s.survivors, s.run, s.killed, s.unconfirmed) == (1, 1, 1, 0)
    # the wide run used early exit, the linked tests were not repeated, the unrelated file never ran
    wide = [c for c in runner.calls if c[0] == "CON" and c[2]]
    assert wide and wide[0][1] == (W1, W2, W3)
    assert all("test_unrelated" not in t for c in runner.calls for t in c[1])
    assert all(T1 not in c[1] and T2 not in c[1] for c in wide)


def test_survivor_nobody_kills_is_an_empty_tuple_not_none(repo: Path) -> None:
    m = measure_mutation(Stage2Runner(KILL_STAGE1, {}), repo, [target()], cfg(stage2=True))
    assert recs(m)["CON"].killed_outside_linked == ()
    assert m.stage2.run == 1 and m.stage2.killed == 0


def test_max_tests_per_mutant_bounds_the_wider_set_deterministically(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W3}})  # only the third test would kill it
    m = measure_mutation(runner, repo, [target()], cfg(stage2=True, stage2_max_tests=2))
    assert recs(m)["CON"].killed_outside_linked == ()  # W3 is beyond the cap: honestly not found
    wide = [c for c in runner.calls if c[0] == "CON" and c[2]]
    assert wide[0][1] == (W1, W2)
    assert any(x.startswith("stage2:tests_capped_at") for x in m.stage2.ladder)


def test_wall_clock_budget_skips_survivors_and_keeps_stage1(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W1}}, advance=40.0)
    m = measure_mutation(
        runner, repo, [target()], cfg(stage2=True, stage2_wall_clock_seconds=100.0), clock=runner.clock
    )
    # the stage-1 loop and the two wide baselines burn the clock; whatever stage 2 could not
    # reach is reported as skipped, never invented
    assert m.status == "measured"
    s = m.stage2
    assert s.killed == 0 and (s.skipped_for_budget >= 1 or any("budget" in x for x in s.ladder))
    assert recs(m)["CON"].status == "survived" and recs(m)["CON"].killed_outside_linked is None


def test_kill_must_repeat_flaky_kill_is_not_a_link_gap(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W1}}, flaky_kill=frozenset({"CON"}))
    m = measure_mutation(runner, repo, [target()], cfg(stage2=True))
    assert recs(m)["CON"].killed_outside_linked == ()
    assert (m.stage2.killed, m.stage2.unconfirmed) == (0, 1)


def test_baseline_failing_wide_test_cannot_kill(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W1}}, wide_failing_baseline=frozenset({W1}))
    m = measure_mutation(runner, repo, [target()], cfg(stage2=True))
    assert recs(m)["CON"].killed_outside_linked == ()
    wide = [c for c in runner.calls if c[0] == "CON" and c[2]]
    assert W1 not in wide[0][1]


def test_runner_error_in_stage2_leaves_stage1_untouched(repo: Path) -> None:
    runner = Stage2Runner(KILL_STAGE1, {"CON": {W1}}, error_ops=frozenset({"CON"}))
    m = measure_mutation(runner, repo, [target()], cfg(stage2=True))
    con = recs(m)["CON"]
    assert con.status == "survived" and con.killed_outside_linked is None
    assert m.stage2.errors == 1 and m.status == "measured"


def test_cache_keeps_stage1_valid_and_serves_stage2(repo: Path) -> None:
    cache: dict = {}
    first = Stage2Runner(KILL_STAGE1, {"CON": {W2}})
    m1 = measure_mutation(first, repo, [target()], cfg(stage2=True), cache=cache, image_digest=IMAGE)
    assert m1.cache_hits == 0 and recs(m1)["CON"].killed_outside_linked == (W2,)
    # stage 1 only, same cache: every stage-1 result is a hit (keys unchanged by stage 2)
    s1 = Stage2Runner(KILL_STAGE1, {"CON": {W2}})
    m_s1 = measure_mutation(s1, repo, [target()], cfg(), cache=cache, image_digest=IMAGE)
    assert m_s1.cache_hits == m1.sampled
    # stage 1 + 2 again: no mutant run at all (the wide baselines still run)
    again = Stage2Runner(KILL_STAGE1, {"CON": {W2}})
    m2 = measure_mutation(again, repo, [target()], cfg(stage2=True), cache=cache, image_digest=IMAGE)
    assert recs(m2)["CON"].killed_outside_linked == (W2,)
    assert m2.stage2.cache_hits == 1
    assert [c for c in again.calls if c[0] not in (None, "CONTROL")] == []


def test_local_runner_still_needs_explicit_opt_in_with_stage2(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_MUTATION_ALLOW_LOCAL", "1")
    local = SubprocessLocalRunner(repo)
    with pytest.raises(LocalRunnerRefusedError):
        measure_mutation(local, repo, [target()], cfg(stage2=True))


def test_invalid_stage2_config_is_rejected() -> None:
    for bad in ({"stage2_max_tests": 0}, {"stage2_wall_clock_seconds": 0}, {"stage2_max_files": 0}):
        with pytest.raises(ValueError):
            MeasureConfig(**bad)


def test_unsafe_wide_test_ids_never_reach_the_command_line(repo: Path) -> None:
    runner = Stage2Runner(
        KILL_STAGE1, {}, wide_tests=("tests/test_wide.py::test_w1", "--evil", "../x.py::t")
    )
    measure_mutation(runner, repo, [target()], cfg(stage2=True))
    sent = {t for c in runner.calls for t in c[1]}
    assert "--evil" not in sent and "../x.py::t" not in sent


def test_mutant_outcome_type_is_reused_for_cache_values() -> None:
    assert MutantOutcome("m", "killed", frozenset({W1})).killed_by == frozenset({W1})
