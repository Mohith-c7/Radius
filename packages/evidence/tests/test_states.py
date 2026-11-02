"""VD-02: per-criterion states, flags, UIM and intent coverage."""

from __future__ import annotations

import pytest
from radius_evidence.domain.config import RuleConfig, SupportConfig, VerdictV2Config
from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import (
    CriterionInput,
    CriterionSymbolEdgeInput,
    SymbolInput,
)
from radius_evidence.domain.quality import STATUS_COUNTED, EvidenceQuality, gated
from radius_evidence.domain.states import (
    CriterionStateResult,
    compute_uim,
    evaluate_criterion,
    intent_coverage,
)
from radius_evidence.domain.support import compute_support

CFG = VerdictV2Config()
P, W, U, C, X = (
    SupportState.PROVEN,
    SupportState.WEAK,
    SupportState.UNEVIDENCED,
    SupportState.CONTRADICTED,
    SupportState.EXCLUDED,
)


def crit(
    cid="c1", *, weight=1.0, testability="behavioral_testable", lifecycle="confirmed"
):
    return CriterionInput(cid, "text", weight, testability, lifecycle)


def row(
    eid="e",
    term=0.2,
    *,
    status=STATUS_COUNTED,
    a=1.0,
    l_cs=1.0,
    l_st=0.9,
    r_ct=1.0,
    tamper=0.0,
    flaky=1.0,
    f=1.0,
    crit_id="c1",
    group="s",
):
    return EvidenceQuality(
        evidence_id=eid,
        criterion_id=crit_id,
        a_static=a,
        d_eff=min(a, 0.6),
        cap_static=0.6,
        i=0.8,
        f=f,
        flaky_f=flaky,
        tamper_penalty=tamper,
        q=term,
        l_cs=l_cs,
        l_st=l_st,
        r_ct=r_ct,
        l=l_cs * l_st * r_ct,
        term=term,
        status=status,
        group_symbol=group,
    )


def support_of(rows, cfg=CFG):
    return compute_support("c1", rows, cfg.support)


def ev(rows=(), c=None, **kw):
    return evaluate_criterion(c or crit(), support_of(list(rows)), CFG, **kw)


# ---- state table: one case per row, in order ------------------------------


@pytest.mark.parametrize(
    ("c", "code"),
    [
        (crit(testability="subjective_or_vague"), "not_testable"),
        (crit(testability="vague"), "not_testable"),
        (crit(testability="untestable_external"), "not_testable"),
        (crit(lifecycle="rejected"), "rejected"),
        (crit(lifecycle="orphaned"), "rejected"),
    ],
)
def test_row1_excluded(c, code) -> None:
    res = ev([row(term=0.9)], c)
    assert res.state is X and res.reasons[0].code == code and res.flags == ()


def test_row1_beats_failing_test() -> None:
    res = ev([row(status="gated:outcome_failed")], crit(testability="vague"))
    assert res.state is X


@pytest.mark.parametrize("status", ["gated:outcome_failed", "gated:outcome_error"])
def test_row2_contradicted_even_with_other_passing_support(status) -> None:
    res = ev([row("a", 0.9), row("bad", 0.0, status=status)])
    assert res.state is C
    assert res.reasons[0].code == "failing_linked_test" and res.reasons[0].ref == "bad"


def test_row2_lists_all_failing_ids_sorted() -> None:
    res = ev(
        [
            row("z", status="gated:outcome_failed"),
            row("m", status="gated:outcome_error"),
        ]
    )
    assert res.reasons[0].ref == "m,z"


def test_row2_failure_beats_non_functional() -> None:
    res = ev(
        [row(status="gated:outcome_failed")],
        crit(testability="non_functional_measurable"),
    )
    assert res.state is C


@pytest.mark.parametrize(
    "bad",
    [
        row(status="gated:outcome_failed", r_ct=0.0),
        row(status="gated:outcome_failed", l_st=0.0),
        row(status="gated:outcome_failed", l_cs=0.0),
        row(status="gated:outcome_skipped"),
        row(status="gated:outcome_flaky"),
        row(status="gated:outcome_not_run"),
        row(status="gated:outcome_failed", crit_id="other"),
    ],
)
def test_row2_unattached_or_nonfailing_items_do_not_contradict(bad) -> None:
    assert ev([bad]).state is not C


@pytest.mark.parametrize("t", ["non_functional_measurable", "non_functional"])
def test_row3_non_functional_unevidenced_with_flag(t) -> None:
    res = ev([row(term=0.9)], crit(testability=t))
    assert res.state is U and Flag.NEEDS_TYPED_EVIDENCE in res.flags
    assert res.reasons[0].code == "needs_typed_evidence"


def test_row4_proven_needs_strong_item() -> None:
    res = ev([row("a", 0.432), row("b", 0.432)])
    assert res.state is P and res.reasons[0].code == "strong_support"


def test_row5_high_support_without_strong_item_is_weak() -> None:
    res = ev([row(f"e{i}", 0.4, a=0.35, group=f"g{i}") for i in range(3)])
    assert res.state is W and Flag.NO_STRONG_ASSERTION in res.flags
    assert res.reasons[0].code == "no_strong_assertion"


def test_row6_weak_band() -> None:
    res = ev([row(term=0.3, a=0.3)])
    assert res.state is W and Flag.NO_STRONG_ASSERTION not in res.flags


def test_row7_unevidenced_without_tests_has_no_linked_test_flag() -> None:
    res = ev([])
    assert res.state is U and Flag.NO_LINKED_TEST in res.flags
    assert {r.code for r in res.reasons} == {"insufficient_support", "no_linked_test"}


def test_row7_with_addressed_edge_but_no_counted_items_has_no_flag() -> None:
    res = ev([row(term=0.0, status=gated("zero_quality"))])
    assert res.state is U and Flag.NO_LINKED_TEST not in res.flags


def test_n_addressed_tests_overrides_row_derivation() -> None:
    assert Flag.NO_LINKED_TEST not in ev([], n_addressed_tests=1).flags
    assert (
        Flag.NO_LINKED_TEST
        in ev([row(term=0.0, status=gated("zero_quality"))], n_addressed_tests=0).flags
    )


# ---- thresholds: every boundary --------------------------------------------


@pytest.mark.parametrize(
    ("S_target", "state"),
    [
        (0.0, U),
        (0.1, U),
        (0.1999, U),
        (0.2, W),
        (0.2001, W),
        (0.3, W),
        (0.4999, W),
        (0.5, P),
        (0.5001, P),
        (0.7, P),
        (0.9, P),
    ],
)
def test_threshold_boundaries_default_profile(S_target, state) -> None:
    res = ev([row(term=S_target, a=1.0)]) if S_target > 0 else ev([])
    assert res.state is state


@pytest.mark.parametrize(
    ("tau_support", "tau_weak", "S_target", "state"),
    [
        (0.6, 0.2, 0.55, W),
        (0.6, 0.2, 0.6, P),
        (0.4, 0.2, 0.45, P),
        (0.4, 0.3, 0.25, U),
        (0.4, 0.3, 0.3, W),
        (0.8, 0.5, 0.79, W),
        (0.8, 0.5, 0.49, U),
    ],
)
def test_thresholds_come_from_config(tau_support, tau_weak, S_target, state) -> None:
    cfg = VerdictV2Config(
        support=SupportConfig(tau_support=tau_support, tau_weak=tau_weak)
    )
    sup = compute_support("c1", [row(term=S_target)], cfg.support)
    assert evaluate_criterion(crit(), sup, cfg).state is state


def test_float_noise_at_threshold_is_tolerated() -> None:
    assert ev([row(term=0.1 + 0.4)]).state is P  # 0.5 up to float noise
    assert ev([row(term=0.1 + 0.1)]).state is W  # 0.2 up to float noise


def test_strong_min_boundary() -> None:
    assert ev([row(term=0.6, a=0.5)]).state is P
    assert ev([row(term=0.6, a=0.4999)]).state is W


# ---- flags -------------------------------------------------------------------


def test_flags_always_static_only_and_sorted() -> None:
    res = ev(
        [row(term=0.6, tamper=0.5, flaky=0.8, f=0.0)],
        crit(lifecycle="proposed"),
        results_received=False,
    )
    assert list(res.flags) == sorted(res.flags)
    assert Flag.STATIC_ONLY in res.flags


@pytest.mark.parametrize(
    ("kw", "flag"),
    [
        ({"tamper": 0.2}, Flag.TAMPERED),
        ({"flaky": 0.9}, Flag.FLAKY_EVIDENCE),
        ({"f": 0.0}, Flag.STALE_EVIDENCE),
    ],
)
def test_row_derived_flags(kw, flag) -> None:
    assert flag in ev([row(**kw)]).flags
    assert flag not in ev([row()]).flags


def test_flaky_status_sets_flag() -> None:
    assert Flag.FLAKY_EVIDENCE in ev([row(status="gated:outcome_flaky")]).flags


def test_tampered_param_and_unattached_rows() -> None:
    assert Flag.TAMPERED in ev([], tampered=True).flags
    assert Flag.TAMPERED not in ev([row(tamper=1.0, r_ct=0.0)]).flags


def test_tampered_is_a_flag_not_a_state() -> None:
    res = ev([row(term=0.0, tamper=1.0, status=gated("zero_quality"))])
    assert res.state is U and Flag.TAMPERED in res.flags


@pytest.mark.parametrize(
    ("lifecycle", "has"),
    [
        ("proposed", True),
        ("confirmed", False),
        ("edited", False),
        ("needs_reconfirmation", False),
    ],
)
def test_unconfirmed_flag(lifecycle, has) -> None:
    assert (Flag.UNCONFIRMED in ev([], crit(lifecycle=lifecycle)).flags) is has


def test_pending_results_flag() -> None:
    assert Flag.PENDING_RESULTS in ev([], results_received=False).flags
    assert Flag.PENDING_RESULTS not in ev([]).flags


@pytest.mark.parametrize(
    ("l_cs", "has"), [(0.49, True), (0.5, False), (1.0, False), (0.2, True)]
)
def test_low_link_confidence_only_on_proven(l_cs, has) -> None:
    res = ev([row(term=0.6, l_cs=l_cs)])
    assert res.state is P and (Flag.LOW_LINK_CONFIDENCE in res.flags) is has


def test_low_link_confidence_not_set_when_weak() -> None:
    assert Flag.LOW_LINK_CONFIDENCE not in ev([row(term=0.3, a=0.3, l_cs=0.2)]).flags


def test_link_review_min_is_configurable() -> None:
    cfg = VerdictV2Config(rules=RuleConfig(link_review_min=0.9))
    sup = compute_support("c1", [row(term=0.6, l_cs=0.8)], cfg.support)
    assert Flag.LOW_LINK_CONFIDENCE in evaluate_criterion(crit(), sup, cfg).flags


def test_default_config_is_used_when_omitted() -> None:
    assert evaluate_criterion(crit(), support_of([row(term=0.6)])).state is P


def test_state_result_roundtrip_and_determinism() -> None:
    res = ev([row(term=0.6)])
    assert CriterionStateResult.from_json(res.to_json()) == res
    assert res == ev([row(term=0.6)])


# ---- UIM -----------------------------------------------------------------------


def states(**kw):
    return {k: CriterionStateResult(k, v) for k, v in kw.items()}


@pytest.mark.parametrize(
    ("weights", "st", "uim", "num", "den"),
    [
        ({"a": 1, "b": 1}, {"a": P, "b": P}, 0.0, 0.0, 2.0),
        ({"a": 1, "b": 1}, {"a": P, "b": U}, 0.5, 1.0, 2.0),
        ({"a": 1, "b": 1}, {"a": U, "b": U}, 1.0, 2.0, 2.0),
        (
            {"a": 1, "b": 1, "c": 1, "d": 1},
            {"a": P, "b": W, "c": U, "d": U},
            0.75,
            3.0,
            4.0,
        ),
        ({"a": 0.5, "b": 1.0}, {"a": U, "b": P}, 1 / 3, 0.5, 1.5),
        ({"a": 0.5, "b": 1.0}, {"a": P, "b": U}, 2 / 3, 1.0, 1.5),
        ({"a": 1, "b": 1}, {"a": X, "b": U}, 1.0, 1.0, 1.0),
        ({"a": 1, "b": 1}, {"a": X, "b": P}, 0.0, 0.0, 1.0),
        ({"a": 1, "b": 1}, {"a": C, "b": P}, 0.5, 1.0, 2.0),
        ({"a": 1, "b": 1}, {"a": W, "b": P}, 0.5, 1.0, 2.0),
        ({"a": 1}, {"a": X}, 0.0, 0.0, 0.0),
    ],
)
def test_uim_weights_and_exclusion(weights, st, uim, num, den) -> None:
    criteria = [crit(k, weight=w) for k, w in weights.items()]
    r = compute_uim(criteria, states(**st), 1.0, CFG)
    assert (r.uim, r.numerator, r.denominator) == pytest.approx((uim, num, den))
    assert set(r.excluded_criterion_ids) == {k for k, v in st.items() if v is X}
    assert set(r.unproven_criterion_ids) == {
        k for k, v in st.items() if v not in (P, X)
    }


def test_uim_empty_and_profile_and_coverage_passthrough() -> None:
    r = compute_uim([], {}, 0.4, CFG)
    assert (r.uim, r.intent_coverage, r.profile) == (0.0, 0.4, "alpha-static")
    assert compute_uim([], {}, 1.0, VerdictV2Config(profile="x")).profile == "x"


def test_uim_counts_weak_above_tau_without_strong_item_as_unproven() -> None:
    res = ev([row(f"e{i}", 0.4, a=0.35, group=f"g{i}") for i in range(3)])
    assert res.state is W
    assert compute_uim([crit()], {"c1": res}, 1.0, CFG).uim == 1.0


# ---- intent coverage -----------------------------------------------------------


def sym(sid, path, *, kind="function", behavioral=True, test=False, pseudo=False):
    return SymbolInput(
        sid, path, sid, kind, "python", "modified", behavioral, test, pseudo
    )


def edge(cid, sid, score=0.9):
    return CriterionSymbolEdgeInput(cid, sid, score, 1)


@pytest.mark.parametrize(
    ("symbols", "edges", "active", "expected"),
    [
        ([], [], ["c1"], 1.0),
        ([sym("a", "x.py")], [], ["c1"], 0.0),
        ([sym("a", "x.py")], [edge("c1", "a")], ["c1"], 1.0),
        ([sym("a", "x.py"), sym("b", "y.py")], [edge("c1", "a")], ["c1"], 0.5),
        ([sym("a", "x.py")], [edge("c1", "a", 0.2)], ["c1"], 1.0),  # at link_min_cs
        ([sym("a", "x.py")], [edge("c1", "a", 0.1999)], ["c1"], 0.0),
        ([sym("a", "x.py")], [edge("c1", "a")], [], 0.0),  # criterion excluded
        ([sym("a", "x.py")], [edge("c2", "a")], ["c1"], 0.0),
        ([sym("a", "x.py", behavioral=False)], [], ["c1"], 1.0),
        ([sym("t", "t.py", test=True)], [], ["c1"], 1.0),
        ([sym("f", "README.md", kind="file", pseudo=True)], [], ["c1"], 1.0),
        # same-file rule: module constant next to a linked function
        (
            [sym("a", "x.py"), sym("m", "x.py", kind="module", pseudo=True)],
            [edge("c1", "a")],
            ["c1"],
            1.0,
        ),
        # a linked pseudo symbol does not cover siblings
        (
            [sym("m", "x.py", kind="module", pseudo=True), sym("a", "x.py")],
            [edge("c1", "m")],
            ["c1"],
            0.5,
        ),
        # the <file> pseudo symbol is not counted in B even in a covered file
        (
            [sym("a", "x.py"), sym("f", "x.py", kind="file", pseudo=True)],
            [edge("c1", "a")],
            ["c1"],
            1.0,
        ),
        # fixture 05 shape: 1 of 3 behavioral symbols
        (
            [
                sym("slug", "t.py"),
                sym("round", "b.py"),
                sym("m", "c.py", kind="module", pseudo=True),
            ],
            [edge("c1", "slug")],
            ["c1"],
            1 / 3,
        ),
    ],
)
def test_intent_coverage_cases(symbols, edges, active, expected) -> None:
    assert intent_coverage(symbols, edges, active, 0.2) == pytest.approx(expected)


def test_intent_coverage_threshold_is_a_parameter() -> None:
    s, e = [sym("a", "x.py")], [edge("c1", "a", 0.3)]
    assert intent_coverage(s, e, ["c1"], 0.3) == 1.0
    assert intent_coverage(s, e, ["c1"], 0.31) == 0.0
