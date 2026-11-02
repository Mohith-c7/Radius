"""VD-01: S(c) aggregation (hand-computed goldens, properties, boundaries)."""

from __future__ import annotations

import itertools
import random

import pytest
from radius_evidence.domain.config import SupportConfig
from radius_evidence.domain.quality import STATUS_COUNTED, EvidenceQuality, gated
from radius_evidence.domain.support import (
    UNKNOWN_GROUP,
    SupportResult,
    compute_support,
    support_reasons,
)

CFG = SupportConfig()


def mk(
    eid: str,
    term: float,
    *,
    group: str | None = "s1",
    a: float = 1.0,
    status: str = STATUS_COUNTED,
    crit: str = "c1",
    l_cs: float = 1.0,
) -> EvidenceQuality:
    return EvidenceQuality(
        evidence_id=eid,
        criterion_id=crit,
        a_static=a,
        d_eff=min(a, 0.6),
        cap_static=0.6,
        i=0.8,
        f=1.0,
        flaky_f=1.0,
        tamper_penalty=0.0,
        q=term,
        l_cs=l_cs,
        l_st=0.9,
        r_ct=1.0,
        l=0.9,
        term=term,
        status=status,
        group_symbol=group,
    )


def S(terms, **kw) -> float:
    rows = [mk(f"e{i}", t, **kw) for i, t in enumerate(terms)]
    return compute_support("c1", rows, CFG).S


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, 0.0), (1, 0.432), (2, 0.604), (3, 0.688), (4, 0.734)],
)
def test_design_goldens_strong_tests_same_symbol(n: int, expected: float) -> None:
    assert S([0.432] * n) == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize(("n", "expected"), [(1, 0.18), (2, 0.283)])
def test_design_goldens_truthiness(n: int, expected: float) -> None:
    assert S([0.18] * n) == pytest.approx(expected, abs=0.001)


def test_exact_value_two_same_group() -> None:
    assert S([0.432, 0.432]) == pytest.approx(1 - 0.568 * (1 - 0.432 * 0.7))


def test_distinct_groups_are_not_discounted() -> None:
    rows = [mk("a", 0.432, group="s1"), mk("b", 0.432, group="s2")]
    r = compute_support("c1", rows, CFG)
    assert r.S == pytest.approx(1 - 0.568**2)
    assert all(i.rank_in_group == 0 for i in r.items)


def test_rank_by_term_desc_then_evidence_id() -> None:
    rows = [mk("b", 0.3), mk("a", 0.3), mk("c", 0.5)]
    r = compute_support("c1", rows, CFG)
    by_id = {i.evidence_id: i for i in r.items}
    assert (
        by_id["c"].rank_in_group,
        by_id["a"].rank_in_group,
        by_id["b"].rank_in_group,
    ) == (0, 1, 2)
    assert by_id["b"].discount == pytest.approx(0.49)
    assert by_id["b"].contribution == pytest.approx(0.3 * 0.49)


def test_empty_gives_zero() -> None:
    r = compute_support("c1", [], CFG)
    assert (r.S, r.S_raw, r.n_counted, r.has_strong_item, r.items) == (
        0.0,
        0.0,
        0,
        False,
        (),
    )


def test_only_gated_rows_give_zero_and_are_kept() -> None:
    rows = [
        mk("a", 0.0, status=gated("zero_quality")),
        mk("b", 0.0, status="gated:outcome_failed"),
    ]
    r = compute_support("c1", rows, CFG)
    assert r.S == 0.0 and len(r.items) == 2 and r.n_counted == 0
    assert all(i.contribution is None for i in r.items)


def test_other_criteria_are_ignored() -> None:
    rows = [mk("a", 0.4, crit="c2"), mk("b", 0.4)]
    r = compute_support("c1", rows, CFG)
    assert r.n_counted == 1 and r.S == pytest.approx(0.4)


def test_zero_term_counted_row_is_not_counted() -> None:
    assert compute_support("c1", [mk("a", 0.0)], CFG).n_counted == 0


@pytest.mark.parametrize(
    ("s_cap", "expected"), [(0.9, 0.9), (0.5, 0.5), (1.0, 0.99999)]
)
def test_cap_applies_to_s_but_not_s_raw(s_cap: float, expected: float) -> None:
    cfg = SupportConfig(s_cap=s_cap)
    rows = [mk(f"e{i}", 0.99, group=f"g{i}") for i in range(5)]
    r = compute_support("c1", rows, cfg)
    assert r.S_raw > 0.9999
    assert r.S == pytest.approx(min(r.S_raw, s_cap))
    assert r.S <= s_cap + 1e-12
    assert expected - 1e-4 <= r.S


def test_cap_boundary_uncapped_below() -> None:
    cfg = SupportConfig(s_cap=0.9)
    r = compute_support("c1", [mk("a", 0.9)], cfg)
    assert r.S == pytest.approx(0.9) and r.S_raw == pytest.approx(0.9)


@pytest.mark.parametrize(
    ("a_values", "strong"),
    [
        ([1.0], True),
        ([0.5], True),
        ([0.4999], False),
        ([0.25, 0.25, 0.35], False),
        ([0.25, 0.5], True),
        ([], False),
    ],
)
def test_has_strong_item_boundary(a_values, strong) -> None:
    rows = [mk(f"e{i}", 0.2, a=a, group=f"g{i}") for i, a in enumerate(a_values)]
    assert compute_support("c1", rows, CFG).has_strong_item is strong


def test_strong_item_must_be_counted() -> None:
    rows = [mk("a", 0.0, a=1.0, status=gated("zero_quality")), mk("b", 0.1, a=0.25)]
    assert compute_support("c1", rows, CFG).has_strong_item is False


@pytest.mark.parametrize("rho", [0.0, 0.3, 0.7, 1.0])
def test_rho_ordering(rho: float) -> None:
    cfg = SupportConfig(rho=rho)
    rows = [mk(f"e{i}", 0.3) for i in range(4)]
    s = compute_support("c1", rows, cfg).S
    lower = compute_support("c1", rows, SupportConfig(rho=max(0.0, rho - 0.2))).S
    assert lower <= s + 1e-12


def test_rho_extremes() -> None:
    rows = [mk(f"e{i}", 0.3) for i in range(4)]
    assert compute_support("c1", rows, SupportConfig(rho=0.0)).S == pytest.approx(0.3)
    assert compute_support("c1", rows, SupportConfig(rho=1.0)).S == pytest.approx(
        1 - 0.7**4
    )


def test_rho_discount_ordering_correlated_below_independent() -> None:
    same = [mk(f"e{i}", 0.3, group="g") for i in range(3)]
    diff = [mk(f"e{i}", 0.3, group=f"g{i}") for i in range(3)]
    assert compute_support("c1", same, CFG).S < compute_support("c1", diff, CFG).S


def test_missing_group_falls_back_to_one_correlated_group() -> None:
    rows = [mk("a", 0.3, group=None), mk("b", 0.3, group=None)]
    r = compute_support("c1", rows, CFG)
    assert {i.group_symbol for i in r.items} == {UNKNOWN_GROUP}
    assert r.S == pytest.approx(1 - 0.7 * (1 - 0.21))


def test_order_independent() -> None:
    rows = [
        mk(f"e{i}", t, group=g)
        for i, (t, g) in enumerate(
            [(0.4, "a"), (0.3, "a"), (0.2, "b"), (0.35, "b"), (0.1, "c")]
        )
    ]
    ref = compute_support("c1", rows, CFG)
    for perm in itertools.islice(itertools.permutations(rows), 40):
        assert compute_support("c1", list(perm), CFG) == ref


def test_deterministic_and_input_not_mutated() -> None:
    rows = [mk("a", 0.4), mk("b", 0.2)]
    a = compute_support("c1", rows, CFG)
    assert a == compute_support("c1", rows, CFG)
    assert rows[0].rank_in_group is None


def test_adding_evidence_never_lowers_s() -> None:
    rng = random.Random(11)
    for _ in range(300):
        n = rng.randint(0, 6)
        rows = [
            mk(f"e{i}", rng.random() * 0.8, group=rng.choice("abc")) for i in range(n)
        ]
        extra = mk("x", rng.random() * 0.8, group=rng.choice("abc"))
        before = compute_support("c1", rows, CFG).S
        after = compute_support("c1", [*rows, extra], CFG).S
        assert after >= before - 1e-12


def test_weaker_evidence_never_raises_s() -> None:
    rng = random.Random(5)
    for _ in range(300):
        n = rng.randint(1, 6)
        terms = [rng.random() * 0.8 for _ in range(n)]
        groups = [rng.choice("abc") for _ in range(n)]
        k = rng.randrange(n)
        weaker = list(terms)
        weaker[k] *= rng.random()
        hi = compute_support(
            "c1",
            [
                mk(f"e{i}", t, group=g)
                for i, (t, g) in enumerate(zip(terms, groups, strict=True))
            ],
            CFG,
        ).S
        lo = compute_support(
            "c1",
            [
                mk(f"e{i}", t, group=g)
                for i, (t, g) in enumerate(zip(weaker, groups, strict=True))
            ],
            CFG,
        ).S
        assert lo <= hi + 1e-12


def test_s_always_within_bounds() -> None:
    rng = random.Random(1)
    for _ in range(200):
        rows = [
            mk(f"e{i}", rng.random(), group=rng.choice("ab"))
            for i in range(rng.randint(0, 8))
        ]
        r = compute_support("c1", rows, CFG)
        assert 0.0 <= r.S <= CFG.s_cap and 0.0 <= r.S_raw <= 1.0


def test_adding_proven_quality_test_never_lowers_support_of_weak_set() -> None:
    weak = [mk("w1", 0.18, a=0.25), mk("w2", 0.18, a=0.25)]
    strong = mk("s", 0.432, a=1.0)
    assert (
        compute_support("c1", [*weak, strong], CFG).S
        >= compute_support("c1", weak, CFG).S
    )


@pytest.mark.parametrize(
    ("rows", "codes"),
    [
        ([], {"no_counted_evidence"}),
        ([mk("a", 0.4)], set()),
        ([mk("a", 0.4), mk("b", 0.3)], {"correlated_discount"}),
        ([mk("a", 0.2, a=0.25)], {"no_strong_assertion"}),
        ([mk(f"e{i}", 0.99, group=f"g{i}") for i in range(4)], {"capped_at_s_cap"}),
    ],
)
def test_support_reasons(rows, codes) -> None:
    r = compute_support("c1", rows, CFG)
    assert {x.code for x in support_reasons(r, CFG)} == codes


def test_result_roundtrips_and_defaults() -> None:
    r = compute_support("c1", [mk("a", 0.4), mk("b", 0.3)], CFG)
    assert SupportResult.from_json(r.to_json()) == r
    assert compute_support("c1", [mk("a", 0.4)]).S == pytest.approx(0.4)
    assert r.algo_version == "support-noisyor-1"


def test_group_falls_back_to_path_symbol() -> None:
    from dataclasses import replace

    from radius_evidence.domain.quality import ChainRef

    a = replace(mk("a", 0.3, group=None), path=ChainRef("p1", "t1"))
    b = replace(mk("b", 0.3, group=None), path=ChainRef("p1", "t2"))
    r = compute_support("c1", [a, b], CFG)
    assert {i.group_symbol for i in r.items} == {"p1"}
    assert sorted(i.rank_in_group for i in r.items) == [0, 1]
