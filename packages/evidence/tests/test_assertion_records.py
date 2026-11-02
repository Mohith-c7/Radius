"""EV-01: LK-04 assertion dicts (plain data) become AssertionFeatures; EV-06 scores them."""

from __future__ import annotations

from typing import Any

import pytest
from radius_evidence.domain.assertion_records import (
    MAX_ASSERTIONS_PER_TEST,
    fact_kind,
    features_from_assertion_set,
)
from radius_evidence.domain.enums import AssertKind
from radius_evidence.domain.strength import a_static

TID = "tests/t.py::test_x"


def rec(
    kind: str, line: int = 5, test_id: str = TID, **strength: Any
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "kind": kind,
        "strength_features": strength,
        "location": {"path": "tests/t.py", "line": line, "end_line": line},
        "subject": {"refs": []},
    }


@pytest.mark.parametrize(
    ("kind", "strength", "expected"),
    [
        ("equality", {}, AssertKind.VALUE_EQUALITY),
        ("approx", {}, AssertKind.APPROX_EQUALITY),
        ("membership", {}, AssertKind.MEMBERSHIP),
        ("regex", {}, AssertKind.MEMBERSHIP),
        ("quantified", {}, AssertKind.MEMBERSHIP),
        ("comparison", {}, AssertKind.COMPARISON_BOUND),
        ("length", {}, AssertKind.LENGTH_CHECK),
        ("snapshot", {}, AssertKind.SNAPSHOT),
        ("truthiness", {}, AssertKind.TRUTHINESS),
        ("identity", {}, AssertKind.TRUTHINESS),
        ("disjunction", {}, AssertKind.TRUTHINESS),
        ("none_check", {}, AssertKind.NONE_CHECK),
        ("type_check", {}, AssertKind.TYPE_CHECK),
        ("mock_call", {}, AssertKind.MOCK_CALLED),
        ("unknown_assert", {}, AssertKind.OTHER),
        ("something_new", {}, AssertKind.OTHER),
        (
            "exception",
            {"exception_specificity": "specific_match"},
            AssertKind.EXCEPTION_TYPE_MESSAGE,
        ),
        (
            "exception",
            {"exception_specificity": "specific", "exception_match": True},
            AssertKind.EXCEPTION_TYPE_MESSAGE,
        ),
        ("exception", {"exception_specificity": "specific"}, AssertKind.EXCEPTION_TYPE),
        ("exception", {"exception_specificity": "broad"}, AssertKind.TRUTHINESS),
        ("exception", {}, AssertKind.TRUTHINESS),
        ("warning", {}, AssertKind.EXCEPTION_TYPE),
        (
            "warning",
            {"exception_specificity": "specific_match"},
            AssertKind.EXCEPTION_TYPE_MESSAGE,
        ),
        ("equality", {"dead": True}, AssertKind.TAUTOLOGY),
        ("equality", {"circular": True}, AssertKind.TAUTOLOGY),
        ("equality", {"swallowed": True}, AssertKind.TAUTOLOGY),
        ("equality", {"mock_only": True}, AssertKind.MOCK_CALLED),
        ("mock_call", {"dead": True, "mock_only": True}, AssertKind.TAUTOLOGY),
    ],
)
def test_fact_kind_mapping(kind: str, strength: dict, expected: AssertKind) -> None:
    assert fact_kind(kind, strength)[0] is expected


@pytest.mark.parametrize(
    ("strength", "tokens"),
    [
        ({"in_loop": True}, {"in_loop"}),
        ({"property_based": True}, {"property_based"}),
        ({"helper_depth": 2}, {"helper"}),
        ({"helper_depth": 0}, set()),
        ({"dead": True, "in_loop": True}, {"dead", "in_loop"}),
        ({"mock_only": True}, {"mock_only"}),
        ({"swallowed": True}, {"swallowed"}),
        ({"circular": True}, {"circular"}),
    ],
)
def test_note_tokens(strength: dict, tokens: set[str]) -> None:
    assert set(fact_kind("equality", strength)[1]) == tokens


def test_snapshot_note() -> None:
    assert "snapshot" in fact_kind("snapshot", {})[1]


def test_conversion_end_to_end_scores() -> None:
    data = {
        "tests": [
            {
                "test_id": TID,
                "path": "tests/t.py",
                "line": 4,
                "parametrized": True,
                "case_count": 3,
            },
            {"test_id": "tests/t.py::test_none", "path": "tests/t.py", "line": 30},
        ],
        "assertions": [
            rec("truthiness", 5),
            {
                **rec("equality", 6, distinct_subject_symbols=1),
                "subject": {
                    "refs": [
                        {"name": "f", "qualified": "pkg.f", "symbol_ids": ["s1", "s0"]}
                    ]
                },
            },
        ],
    }
    out = features_from_assertion_set(data)
    assert out.rejected == ()
    by_id = {f.test_id: f for f in out.features}
    f = by_id[TID]
    assert (f.n_assertions, f.is_parametrized, f.n_param_cases) == (2, True, 3)
    assert f.line_start == 4 and f.line_end >= 6
    assert f.called_symbol_refs == ("pkg.f",)
    assert f.assertions[1].target_symbol_ids == ("s0", "s1")
    assert f.assertions[1].compares_computed_value
    assert a_static(f) == 1.0
    assert a_static(by_id["tests/t.py::test_none"]) == 0.0  # summary only: no assertion
    assert [x.test_id for x in out.features] == sorted(by_id)


def test_expects_exception_from_records() -> None:
    out = features_from_assertion_set(
        {"assertions": [rec("exception", exception_specificity="specific")]}
    )
    assert out.features[0].expects_exception
    assert a_static(out.features[0]) == 0.8


def test_term_overrides_are_attached() -> None:
    out = features_from_assertion_set(
        {"assertions": [rec("equality")]},
        name_terms={TID: ("reject", "digit")},
        literal_terms={TID: ("abc",)},
    )
    assert out.features[0].name_terms == ("reject", "digit")
    assert out.features[0].literal_terms == ("abc",)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        "x",
        {"assertions": "no"},
        {"assertions": [None, 1, "x"]},
        {"assertions": [{"kind": "equality"}]},
        {"assertions": [{"test_id": "", "kind": "equality"}]},
        {"tests": [{"path": "a"}, 3]},
    ],
)
def test_malformed_inputs_are_rejected_safely(data: Any) -> None:
    out = features_from_assertion_set(data)
    assert out.features == ()
    assert out.rejected


def test_record_without_kind_is_skipped_but_test_survives() -> None:
    out = features_from_assertion_set(
        {"assertions": [{"test_id": TID}, rec("equality")]}
    )
    assert len(out.features) == 1 and out.features[0].n_assertions == 1
    assert "malformed_assertion_record" in {r.code for r in out.rejected}


def test_oversized_assertion_lists_are_truncated() -> None:
    records = [rec("truthiness", line=i) for i in range(MAX_ASSERTIONS_PER_TEST + 10)]
    out = features_from_assertion_set({"assertions": records})
    assert out.features[0].n_assertions == MAX_ASSERTIONS_PER_TEST
    assert "too_many_assertions" in {r.code for r in out.rejected}


def test_output_is_order_independent() -> None:
    records = [
        rec("equality", 5),
        rec("truthiness", 9),
        rec("none_check", 7, test_id="tests/t.py::a"),
    ]
    a = features_from_assertion_set({"assertions": records})
    b = features_from_assertion_set({"assertions": list(reversed(records))})
    assert a == b
