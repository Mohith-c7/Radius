"""Contract 5: measured d_eff in q(e, c), Stage B kill-matrix use (hand-computed values).

Wilson 95% lower bounds used below (z = 1.96), computed by hand from
``(p + z^2/2n - z*sqrt(p(1-p)/n + z^2/4n^2)) / (1 + z^2/n)``:

* 8/10  -> 0.490157      * 20/20 -> 0.838870      * 0/10 -> 0
* 5/5   -> 0.565509      * 3/10  -> 0.107789
"""

from __future__ import annotations

import random

import pytest
from radius_evidence.domain.config import QualityConfig
from radius_evidence.domain.enums import (
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.inputs import MutantInput, MutationInput, StageAInput
from radius_evidence.domain.model import (
    EvidenceItem,
    FlakyInfo,
    FreshnessInfo,
    IndependenceInfo,
)
from radius_evidence.domain.mutation import (
    BASIS_MEASURED,
    BASIS_MIXED,
    BASIS_STATIC,
    measure_criterion,
    measure_test,
    wilson_interval,
)
from radius_evidence.domain.quality import (
    STATUS_COUNTED,
    MutationMeasure,
    combine_quality,
    evidence_quality_row,
    gated,
)
from radius_evidence.domain.versions import (
    EVIDENCE_QUALITY_MUTATION_VERSION,
    EVIDENCE_QUALITY_VERSION,
)

SHA = "a" * 40


def make_item(*, outcome: Outcome | None = Outcome.PASSED, factor: float = 0.8) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_1",
        kind=EvidenceKind.TEST_OUTCOME,
        source=EvidenceSource.CI_UPLOAD,
        analysis_id="a",
        repository_id="r",
        head_sha=SHA,
        subject_id="tests/t.py::test_x",
        path="tests/t.py",
        symbol_ids=(),
        criterion_ids=(),
        outcome=outcome,
        duration_ms=1,
        features=None,
        severity=None,
        rule_id=None,
        independence=IndependenceInfo(AuthoredBy.UNKNOWN, IndependenceBasis.CHANGED_IN_PR, factor),
        flaky=FlakyInfo(flagged=False),
        freshness=FreshnessInfo(SHA, SHA, 1.0, "current_head"),
        reasons=(),
        collected_at="2026-11-02T10:00:00Z",
    )


CFG = QualityConfig()  # cap_static = 0.60
S1, S2 = "python:src/a.py::f#function@1", "python:src/b.py::g#function@1"
T1, T2 = "tests/test_a.py::test_one", "tests/test_a.py::test_two"


def measure(killed: int, n: int, *, min_decided: int = 5) -> MutationMeasure:
    if n < min_decided:
        return MutationMeasure(killed, n, None, None, False, min_decided)
    lcb, _ = wilson_interval(killed, n)
    return MutationMeasure(killed, n, killed / n, lcb, True, min_decided)


def row(m: MutationMeasure | None, **kw):
    args = {"a_static": 1.0, "w_cs": 1.0, "w_st": 0.9, "r_ct": 1.0, "symbol_id": "sym"}
    args.update(kw)
    return evidence_quality_row(make_item(), "c1", mutation=m, **args)


# ------------------------------------------------------------------ Wilson


@pytest.mark.parametrize(
    ("k", "n", "lcb"),
    [(8, 10, 0.490157), (20, 20, 0.838870), (0, 10, 0.0), (5, 5, 0.565509), (3, 10, 0.107789)],
)
def test_wilson_lower_bound_hand_values(k: int, n: int, lcb: float) -> None:
    assert wilson_interval(k, n)[0] == pytest.approx(lcb, abs=1e-6)
    assert wilson_interval(0, 0) == (0.0, 1.0)


# ------------------------------------------------------------------ q(e, c)


def test_measured_d_eff_is_the_wilson_lower_bound_and_q_follows() -> None:
    r = row(measure(8, 10))
    assert r.basis == "mutation" and r.algo_version == EVIDENCE_QUALITY_MUTATION_VERSION
    assert r.d_eff == pytest.approx(0.490157, abs=1e-6)
    assert r.d_mut == pytest.approx(0.8) and r.d_mut_lcb == pytest.approx(0.490157, abs=1e-6)
    assert (r.mutation_n, r.mutation_killed) == (10, 8)
    # q = d_eff * i * f * flaky * (1 - tamper) with i = 0.8 (make_item default)
    assert r.q == pytest.approx(0.490157 * 0.8, abs=1e-6)
    # term = lambda * q * l with l = 1.0 * 0.9 * 1.0
    assert r.l == pytest.approx(0.9) and r.term == pytest.approx(0.490157 * 0.8 * 0.9, abs=1e-6)
    assert r.status == STATUS_COUNTED


def test_strong_static_test_that_kills_little_is_lowered() -> None:
    static = row(None)
    assert static.d_eff == pytest.approx(0.6) and static.basis == "static"
    assert static.algo_version == EVIDENCE_QUALITY_VERSION and static.mutation_n is None
    weak = row(measure(3, 10))
    assert weak.d_eff == pytest.approx(0.107789, abs=1e-6)
    assert weak.d_eff < static.d_eff
    assert weak.term < static.term
    dead = row(measure(0, 10))
    assert dead.d_eff == 0.0 and dead.q == 0.0 and dead.status == gated("zero_quality")
    assert dead.term == 0.0


def test_measured_detection_can_exceed_the_static_cap() -> None:
    strong = row(measure(20, 20))
    assert strong.d_eff == pytest.approx(0.838870, abs=1e-6)
    assert strong.d_eff > CFG.cap_static
    assert strong.q == pytest.approx(0.838870 * 0.8, abs=1e-6)
    assert strong.term == pytest.approx(0.838870 * 0.8 * 0.9, abs=1e-6)
    assert any(r.code == "d_from_mutation" for r in combine_quality(
        1.0, independence=1.0, freshness=1.0, flaky_f=1.0, tamper_p=0.0, config=CFG,
        mutation=measure(20, 20)).reasons)


def test_five_for_five_is_still_below_the_static_cap() -> None:
    # a small sample cannot buy a better score than static: lcb(5/5) = 0.565509 < 0.60
    assert row(measure(5, 5)).d_eff == pytest.approx(0.565509, abs=1e-6)


def test_insufficient_sample_keeps_the_static_cap_with_a_reason() -> None:
    f = combine_quality(
        1.0, independence=1.0, freshness=1.0, flaky_f=1.0, tamper_p=0.0, config=CFG,
        mutation=measure(4, 4),
    )
    assert f.d_eff == pytest.approx(0.6) and f.basis == "static"
    assert [r.code for r in f.reasons] == ["mutation_insufficient_sample", "capped_static"]
    r = row(measure(4, 4))
    assert r.basis == "static" and r.d_mut is None and r.d_mut_lcb is None
    assert (r.mutation_n, r.mutation_killed) == (4, 4)  # the sample size is still reported


def test_no_assertion_test_cannot_be_rescued_by_kills() -> None:
    f = combine_quality(
        0.0, independence=1.0, freshness=1.0, flaky_f=1.0, tamper_p=0.0, config=CFG,
        mutation=measure(10, 10),
    )
    assert f.d_eff == 0.0 and f.q == 0.0 and f.basis == "static"
    assert {r.code for r in f.reasons} == {"zero_a_static", "mutation_ignored_zero_a"}


def test_unmeasured_is_never_better_than_static_property() -> None:
    rng = random.Random(11)
    for _ in range(300):
        a, i, f = rng.random(), rng.random(), rng.choice([0.0, 1.0])
        none = combine_quality(a, independence=i, freshness=f, flaky_f=1.0, tamper_p=0.0, config=CFG)
        n = rng.randrange(0, 5)
        small = combine_quality(
            a, independence=i, freshness=f, flaky_f=1.0, tamper_p=0.0, config=CFG,
            mutation=measure(rng.randrange(0, n + 1), n),
        )
        assert small.d_eff == none.d_eff and small.q == none.q <= min(CFG.cap_static, a) + 1e-12


def test_other_factors_still_apply_to_measured_d_eff() -> None:
    f = combine_quality(
        1.0, independence=0.5, freshness=1.0, flaky_f=0.5, tamper_p=0.5, config=CFG,
        mutation=measure(20, 20),
    )
    assert f.q == pytest.approx(0.838870 * 0.5 * 0.5 * 0.5, abs=1e-6)
    stale = combine_quality(
        1.0, independence=1.0, freshness=0.0, flaky_f=1.0, tamper_p=0.0, config=CFG,
        mutation=measure(20, 20),
    )
    assert stale.q == 0.0  # a stale test counts for nothing, measured or not


@pytest.mark.parametrize("outcome", [Outcome.FAILED, Outcome.ERROR])
def test_mutation_can_never_turn_a_failing_test_into_support(outcome: Outcome) -> None:
    for m in (None, measure(20, 20), measure(0, 10), measure(3, 4)):
        r = evidence_quality_row(
            make_item(outcome=outcome), "c1", a_static=1.0, w_cs=1.0, w_st=0.9, r_ct=1.0,
            symbol_id="s", mutation=m,
        )
        assert r.status == gated("outcome_" + outcome.value)
        assert r.term == 0.0


# ------------------------------------------------------------------ Stage B helpers


def mutants(spec: list[tuple[str, str, str, tuple[str, ...], bool]]) -> tuple[MutantInput, ...]:
    return tuple(
        MutantInput(f"m{i}", sym, "src/a.py", 10 + i, op, status, killed, suspect)
        for i, (sym, op, status, killed, suspect) in enumerate(spec)
    )


def matrix() -> MutationInput:
    """10 decided mutants of S1: T1 kills m0-m7, T2 kills m0-m2; 2 survivors; 1 timeout; 1 suspect."""

    both = (T1, T2)
    rows = [(S1, "ROR", "killed", both, False)] * 3
    rows += [(S1, "AOR", "killed", (T1,), False)] * 5
    rows += [(S1, "CON", "survived", (), False)] * 2
    rows += [(S1, "RET", "timeout", (), False), (S1, "NEG", "survived", (), True)]
    return MutationInput(
        status="measured", mutants=mutants(rows), symbol_tests={S1: (T1, T2)}, min_decided=5
    )


def test_measure_test_counts_only_decided_non_equivalent_mutants() -> None:
    m = matrix()
    a = measure_test(m, {S1}, T1)
    b = measure_test(m, {S1}, T2)
    assert (a.killed, a.n, a.measured) == (8, 10, True)
    assert a.d_mut == pytest.approx(0.8) and a.lcb == pytest.approx(0.490157, abs=1e-6)
    assert (b.killed, b.n) == (3, 10) and b.lcb == pytest.approx(0.107789, abs=1e-6)


def test_measure_test_none_when_no_data_for_the_pair() -> None:
    m = matrix()
    assert measure_test(None, {S1}, T1) is None  # flag off
    assert measure_test(m, {S2}, T1) is None  # symbols the test was never run against
    assert measure_test(m, {S1}, "tests/other.py::t") is None  # a test that was not run
    unmeasured = MutationInput(status="unmeasured", reason="sandbox_disabled")
    assert measure_test(unmeasured, {S1}, T1) is None


def test_measure_test_small_sample_is_not_measured() -> None:
    small = MutationInput(
        status="measured",
        mutants=mutants([(S1, "ROR", "killed", (T1,), False)] * 4),
        symbol_tests={S1: (T1,)},
    )
    m = measure_test(small, {S1}, T1)
    assert (m.killed, m.n, m.measured, m.lcb) == (4, 4, False, None)


def test_criterion_union_survivors_and_exclusions() -> None:
    cm = measure_criterion(matrix(), {S1}, [T1, T2], {T1, T2})
    assert cm.basis == BASIS_MEASURED
    assert (cm.n_mutants, cm.killed) == (10, 8)
    assert cm.d_union == pytest.approx(0.8) and cm.d_union_lcb == pytest.approx(0.490157, abs=1e-6)
    assert [(s.mutant_id, s.line, s.operator) for s in cm.survivors] == [("m8", 18, "CON"), ("m9", 19, "CON")]
    assert cm.excluded == {"timeout": 1, "equivalent_suspect": 1}
    assert cm.d_reach is None and cm.d_reach_reason == "no_reachability_data"
    only_t2 = measure_criterion(matrix(), {S1}, [T2], {T2})
    assert only_t2.killed == 3 and len(only_t2.survivors) == 7  # T2 alone leaves 7 gaps


def test_criterion_basis_static_mixed_and_flag_off() -> None:
    assert measure_criterion(None, {S1}, [T1], set()).basis == BASIS_STATIC
    assert measure_criterion(matrix(), {S1}, [T1, T2], {T1}).basis == BASIS_MIXED
    assert measure_criterion(matrix(), {S1}, [T1], set()).basis == BASIS_STATIC
    off = measure_criterion(MutationInput(status="unmeasured", reason="no_stable_linked_tests"),
                            {S1}, [T1], set())
    assert off.basis == BASIS_STATIC and off.reason == "no_stable_linked_tests" and off.survivors == ()


def test_stage_a_input_roundtrips_and_defaults_to_none() -> None:
    assert StageAInput.__dataclass_fields__["mutation"].default is None
    m = matrix()
    again = MutationInput.from_dict(m.to_dict())
    assert again == m
