"""EV-06: a_static is the design formula (max of the kind table) with reason codes."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest
from radius_evidence.domain.config import DEFAULT_ASSERTION_SCORES, QualityConfig
from radius_evidence.domain.enums import AssertKind
from radius_evidence.domain.model import AssertionFact, AssertionFeatures
from radius_evidence.domain.strength import a_static, explain_a_static, kind_score


def feat(
    *kinds: AssertKind | tuple[AssertKind, str],
    expects_exception: bool = False,
    skip: bool = False,
    param: int | None = None,
) -> AssertionFeatures:
    facts = []
    for i, k in enumerate(kinds):
        kind, note = k if isinstance(k, tuple) else (k, None)
        facts.append(AssertionFact(kind, line=10 + i, note=note))
    return AssertionFeatures(
        test_id="tests/t.py::test_x",
        path="tests/t.py",
        line_start=9,
        line_end=20,
        assertions=tuple(facts),
        n_assertions=len(facts),
        expects_exception=expects_exception,
        is_parametrized=param is not None,
        n_param_cases=param,
        has_skip_marker=skip,
        name_terms=(),
        literal_terms=(),
    )


@pytest.mark.parametrize("kind", list(AssertKind))
def test_single_fact_equals_table_entry(kind: AssertKind) -> None:
    assert a_static(feat(kind)) == DEFAULT_ASSERTION_SCORES[kind.value]


@pytest.mark.parametrize("kind", list(AssertKind))
def test_every_kind_has_a_table_entry(kind: AssertKind) -> None:
    assert kind.value in DEFAULT_ASSERTION_SCORES


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        ((AssertKind.TRUTHINESS, AssertKind.VALUE_EQUALITY), 1.0),
        ((AssertKind.TYPE_CHECK, AssertKind.NONE_CHECK), 0.25),
        ((AssertKind.TAUTOLOGY, AssertKind.MOCK_CALLED), 0.20),
        ((AssertKind.SNAPSHOT, AssertKind.LENGTH_CHECK), 0.30),
        ((AssertKind.MEMBERSHIP, AssertKind.COMPARISON_BOUND), 0.35),
        ((AssertKind.EXCEPTION_TYPE, AssertKind.EXCEPTION_TYPE_MESSAGE), 0.90),
        ((AssertKind.APPROX_EQUALITY, AssertKind.EXCEPTION_TYPE_MESSAGE), 0.90),
        ((AssertKind.TAUTOLOGY, AssertKind.NO_ASSERTION, AssertKind.OTHER), 0.0),
    ],
)
def test_max_over_facts(kinds: tuple[AssertKind, ...], expected: float) -> None:
    assert a_static(feat(*kinds)) == expected


@pytest.mark.parametrize(
    ("features", "expected", "code"),
    [
        (feat(), 0.0, "no_assertion"),
        (feat(expects_exception=True), 0.80, "exception_only"),
        (feat(AssertKind.TAUTOLOGY), 0.0, "no_effective_assertion"),
        (feat(AssertKind.VALUE_EQUALITY, skip=True), 1.0, "skip_marker"),
        (feat(AssertKind.VALUE_EQUALITY, param=3), 1.0, "parametrized"),
        (feat(AssertKind.VALUE_EQUALITY, param=None), 1.0, "assert_value_equality"),
    ],
)
def test_edge_cases_and_reason_codes(
    features: AssertionFeatures, expected: float, code: str
) -> None:
    result = explain_a_static(features)
    assert result.score == expected
    assert code in {r.code for r in result.reasons}


@pytest.mark.parametrize(
    ("note", "code"),
    [
        ("mock_only", "mock_only"),
        ("circular", "circular_expectation"),
        ("dead", "dead_assertion"),
        ("swallowed", "swallowed_assertion"),
        ("in_loop", "assertion_in_loop"),
        ("property_based", "property_based"),
        ("snapshot", "snapshot_only"),
        ("helper", "via_helper"),
        ("in_loop helper", "via_helper"),
        ("IN_LOOP,property_based", "property_based"),
    ],
)
def test_note_tokens_become_reason_codes(note: str, code: str) -> None:
    result = explain_a_static(feat((AssertKind.VALUE_EQUALITY, note)))
    assert code in {r.code for r in result.reasons}
    assert result.score == 1.0  # notes never change the score


def test_unknown_note_token_is_ignored() -> None:
    result = explain_a_static(feat((AssertKind.TRUTHINESS, "whatever")))
    assert {r.code for r in result.reasons} == {"assert_truthiness"}


def test_best_kind_reported_and_ties_are_stable() -> None:
    r = explain_a_static(feat(AssertKind.MEMBERSHIP, AssertKind.COMPARISON_BOUND))
    assert r.best_kind is AssertKind.MEMBERSHIP  # first by (line, kind) on equal score


def test_unknown_kind_string_scores_zero() -> None:
    assert kind_score("not_a_kind") == 0.0


def test_custom_table_is_honoured_and_clamped() -> None:
    cfg = QualityConfig(assertion_scores={"value_equality": 7.0, "truthiness": -1.0})
    assert a_static(feat(AssertKind.VALUE_EQUALITY), cfg) == 1.0
    assert a_static(feat(AssertKind.TRUTHINESS), cfg) == 0.0


def test_cap_static_is_not_applied_here() -> None:
    assert (
        a_static(feat(AssertKind.VALUE_EQUALITY), QualityConfig(cap_static=0.1)) == 1.0
    )


def test_fact_order_does_not_change_score_or_reasons() -> None:
    kinds = [AssertKind.TRUTHINESS, AssertKind.VALUE_EQUALITY, AssertKind.NONE_CHECK]
    base = feat(*kinds)
    shuffled = replace(base, assertions=tuple(reversed(base.assertions)))
    assert explain_a_static(base) == explain_a_static(shuffled)


def test_deterministic_repeat() -> None:
    f = feat(AssertKind.EXCEPTION_TYPE, AssertKind.MOCK_CALLED, param=2)
    assert [explain_a_static(f) for _ in range(3)] == [explain_a_static(f)] * 3


def test_property_more_weak_facts_never_raise_score() -> None:
    weak = [
        k
        for k in AssertKind
        if DEFAULT_ASSERTION_SCORES[k.value] <= 0.35 and k is not AssertKind.OTHER
    ]
    rng = random.Random(7)
    for _ in range(200):
        base = [rng.choice(weak) for _ in range(rng.randint(0, 4))]
        before = a_static(feat(*base))
        extra = a_static(feat(*base, rng.choice(weak)))
        assert extra >= before  # adding a fact can only raise the max...
        ceiling = max([DEFAULT_ASSERTION_SCORES[k.value] for k in base] + [0.35])
        assert extra <= ceiling  # ...but never beyond the weak ceiling


def test_property_monotone_in_each_kind_score() -> None:
    rng = random.Random(11)
    kinds = list(AssertKind)
    for _ in range(100):
        facts = [rng.choice(kinds) for _ in range(rng.randint(1, 4))]
        target = rng.choice(facts)
        lo = dict(DEFAULT_ASSERTION_SCORES)
        hi = dict(DEFAULT_ASSERTION_SCORES)
        hi[target.value] = min(1.0, lo[target.value] + 0.2)
        f = feat(*facts)
        assert a_static(f, QualityConfig(assertion_scores=hi)) >= a_static(
            f, QualityConfig(assertion_scores=lo)
        )


def test_score_always_in_unit_interval() -> None:
    rng = random.Random(3)
    kinds = list(AssertKind)
    for _ in range(200):
        f = feat(*[rng.choice(kinds) for _ in range(rng.randint(0, 6))])
        assert 0.0 <= a_static(f) <= 1.0
