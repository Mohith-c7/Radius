"""Table-driven tests of criterion -> test relevance ``r_ct`` (VS-04)."""

from __future__ import annotations

import json
import random

import pytest
from radius_linking.application.relevance import (
    RelevanceConfig,
    assertion_signal,
    canonical_terms,
    connected_pairs,
    criterion_facets,
    hint_matches,
    lexical_signal,
    name_signal,
    relevance_from_links,
    relevant_tests,
    score_relevance,
    specificity_factor,
)
from radius_linking.domain import (
    COMBINED,
    AssertionFact,
    CriterionInput,
    CriterionTestRelevance,
    Link,
    RelevanceReason,
    RelevanceSet,
    SymbolTestEdge,
    TestDoc,
)
from radius_linking.domain.bm25 import BM25Index

CFG = RelevanceConfig()
SYM = "src/validators.py::validate_password"


def A(subject="", expected="", kind="equality", names=(), exc=""):
    return AssertionFact(subject, expected, kind, tuple(names), exc)


def T(name, *facts, doc="", params=(), lits=(), path="tests/test_v.py"):
    return TestDoc(
        f"{path}::{name}", name, doc, tuple(params), tuple(facts), tuple(lits)
    )


def C(cid, text, tests=()):
    return CriterionInput(cid, text, tests=tuple(tests))


def run(criteria, docs, sym=SYM, cfg=None):
    conn = {(c.criterion_id, d.test_id): (sym,) for c in criteria for d in docs}
    return score_relevance(criteria, docs, conn, cfg)


def VP(*facts):
    return A("validate_password('x')", "False", names=("validate_password",))


# --------------------------------------------------------------------------- vocabulary

CANON_CASES = [
    ("raises", ["reject"]),
    ("Rejects the input", ["reject", "input"]),
    ("eight characters", ["8", "character"]),
    ("a hundred", ["100"]),
    ("trims whitespace", ["strip", "strip"]),
    ("applyDiscount", ["apply", "discount"]),
    ("ValueError", ["value", "reject"]),
    ("the and of", []),
    ("maximum limit", ["maximum", "boundary"]),
    ("INVALID input", ["reject", "input"]),
]


@pytest.mark.parametrize("text,expected", CANON_CASES)
def test_canonical_terms(text, expected):
    assert canonical_terms(text) == expected


FACET_CASES = [
    (
        "raises ValueError for empty input",
        dict(exceptions=("valueerror",), error_class=True),
    ),
    ("returns the price", dict(exceptions=(), error_class=False, constraint=False)),
    (
        "responds with status 404 when missing",
        dict(statuses=("404",), error_class=True),
    ),
    ("returns 200 OK", dict(statuses=(), numbers=("200",))),
    ("http status 200 is returned", dict(statuses=("200",), error_class=False)),
    ("rounds to 2 decimals", dict(numbers=("2",))),
    ("a password needs at least 8 characters", dict(constraint=True, numbers=("8",))),
    (
        "a password needs at least eight characters",
        dict(constraint=True, numbers=("8",)),
    ),
    ("rejects the 'abc' token", dict(quoted=("abc",), error_class=True)),
    ("the '-' char is removed", dict(quoted=())),
    ("uses `parse_duration` helper", dict(quoted=("parse_duration",))),
    ("calls load_config on start", dict(identifiers=("load_config",))),
    ("raises OutOfStock when empty", dict(exceptions=("outofstock",))),
    ("Shows a Nice Message", dict(exceptions=())),
    ("percent outside 0..100 raises ValueError", dict(numbers=("0", "100"))),
    ("returns 500 items", dict(statuses=("500",), error_class=True)),
]


@pytest.mark.parametrize("text,expect", FACET_CASES)
def test_criterion_facets(text, expect):
    f = criterion_facets(text)
    for key, value in expect.items():
        assert getattr(f, key) == value, (key, f)


def test_facets_exclude_symbol_identifiers():
    f = criterion_facets(
        "calls validate_password and load_config", frozenset({"validate_password"})
    )
    assert f.identifiers == ("load_config",)
    assert f.has_anchors
    assert not criterion_facets("plain words only").has_anchors


HINT_CASES = [
    ("tests/test_v.py::test_a", "tests/test_v.py::test_a", True),
    ("test_a", "tests/test_v.py::test_a", True),
    ("tests/test_v.py", "tests/test_v.py::test_a", True),
    ("test_v.py", "tests/test_v.py::test_a", True),
    ("tests\\test_v.py", "tests/test_v.py::test_a", True),
    ("test_b", "tests/test_v.py::test_a", False),
    ("", "tests/test_v.py::test_a", False),
    ("   ", "tests/test_v.py::test_a", False),
    ("tests/test_w.py", "tests/test_v.py::test_a", False),
    ("est_a", "tests/test_v.py::test_a", False),
]


@pytest.mark.parametrize("hint,tid,ok", HINT_CASES)
def test_hint_matches(hint, tid, ok):
    assert hint_matches(hint, tid) is ok


SPEC_CASES = [
    (0, 1.0),
    (1, 1.0),
    (2, 1.0),
    (3, 1 / 1.15),
    (4, 1 / 1.3),
    (6, 1 / 1.6),
    (10, 0.5),
    (50, 0.5),
]


@pytest.mark.parametrize("n,expected", SPEC_CASES)
def test_specificity_factor(n, expected):
    assert specificity_factor(n, CFG) == pytest.approx(max(0.5, expected))


def test_specificity_is_monotone_non_increasing():
    vals = [specificity_factor(n, CFG) for n in range(20)]
    assert vals == sorted(vals, reverse=True)


# --------------------------------------------------------------------------- signals


NAME_CASES = [
    ("test_rejects_missing_digit", "a password needs at least one digit", 1 / 3),
    ("test_rejects_seven_characters", "a password needs at least 8 characters", 1 / 3),
    ("test_accepts_eight_characters", "a password needs at least 8 characters", 2 / 3),
    ("test_validate_password", "a password needs at least 8 characters", 0.0),
    ("test_x", "anything", 0.0),
    ("test_zzz_qqq", "a password needs a digit", 0.0),
    ("testRejectsDigit", "password needs a digit and rejects", 1.0),
]


@pytest.mark.parametrize("name,text,expected", NAME_CASES)
def test_name_signal(name, text, expected):
    sig = name_signal(
        T(name), criterion_facets(text), frozenset({"validate", "password"})
    )
    assert sig.score == pytest.approx(expected)
    assert sig.code == "name_convention"


def _index(docs):
    from radius_linking.application.relevance import _bm25_tokens

    return BM25Index({d.test_id: _bm25_tokens(d) for d in docs})


def test_lexical_signal_scores_and_removes_symbol_terms():
    docs = [T("test_uppercase_rule"), T("test_other_thing"), T("test_third")]
    idx = _index(docs)
    f = criterion_facets("a password needs an uppercase letter")
    hit = lexical_signal(idx, docs[0].test_id, f, frozenset({"password"}), 1.5)
    miss = lexical_signal(idx, docs[1].test_id, f, frozenset({"password"}), 1.5)
    assert hit.score > 0.1 and miss.score == 0.0
    assert "uppercase" in hit.detail
    empty = lexical_signal(
        idx, docs[0].test_id, criterion_facets("password"), frozenset({"password"}), 1.5
    )
    assert empty.score == 0.0 and "no criterion terms" in empty.detail


def test_lexical_scale_is_clamped_to_one():
    docs = [T("test_alpha_beta")]
    sig = lexical_signal(
        _index(docs),
        docs[0].test_id,
        criterion_facets("alpha beta"),
        frozenset(),
        100.0,
    )
    assert sig.score == 1.0


ASSERT_CASES = [
    # (criterion text, test, expected anchor score, expected exception score)
    (
        "raises ValueError",
        T("t", A("f(1)", "ValueError", "exception", exc="ValueError")),
        1.0,
        1.0,
    ),
    (
        "raises ValueError",
        T("t", A("f(1)", "KeyError", "exception", exc="KeyError")),
        0.0,
        0.4,
    ),
    ("raises ValueError", T("t", A("f(1)", "1", "equality")), 0.0, 0.0),
    (
        "raises an error",
        T("t", A("f(1)", "TypeError", "exception", exc="TypeError")),
        0.0,
        0.4,
    ),
    ("returns 404 status", T("t", A("r.status", "404")), 1.0, 0.0),
    ("returns 404 status", T("t", A("r.status", "200")), 0.0, 0.0),
    ("rounds to 2 decimals", T("t", A("round_it(1.234)", "1.23")), 0.0, 0.0),
    ("handles the 100 case", T("t", A("f(100)", "0")), 1.0, 0.0),
    (
        "handles 100 and 5",
        T("t", A("f(100)", "0")),
        0.5 / 1.0 * 1.0 / 1.0 * 1.0 if False else 1 / 2,
        0.0,
    ),
    ("rejects the 'abc' token", T("t", A("f('abc')", "False")), 1.0, 0.0),
    ("calls load_config", T("t", A("load_config()", "1")), 1.0, 0.0),
    ("calls load_config", T("t", lits=("load_config",)), 1.0, 0.0),
    ("plain words", T("t", A("f()", "1")), 0.0, 0.0),
    ("raises ValueError", T("t", params=("ValueError",)), 1.0, 0.0),
]


@pytest.mark.parametrize("text,doc,anchor,exc", ASSERT_CASES)
def test_assertion_signal(text, doc, anchor, exc):
    a, e = assertion_signal(doc, criterion_facets(text), CFG)
    assert a.score == pytest.approx(anchor)
    assert e.score == pytest.approx(exc)


# --------------------------------------------------------------------------- end to end

DIGIT = C("C2", "a password needs at least one digit")
LENGTH = C("C1", "a password needs at least 8 characters")
UPPER = C("C3", "a password needs at least one uppercase letter")
COMMON = C(
    "C4", "a password must not be on the common-password list (case-insensitive)"
)

F08 = [
    T("test_rejects_seven_characters", VP()),
    T("test_accepts_eight_characters", VP()),
    T("test_rejects_missing_digit", VP()),
    T(
        "test_uppercase_rule_runs",
        A(
            "isinstance(validate_password('a'), bool)",
            "bool",
            "type_check",
            ("validate_password",),
        ),
    ),
    T("test_is_blank", A("is_blank('  ')", "", "truthiness", ("is_blank",))),
]
F08_CRIT = [LENGTH, DIGIT, UPPER, COMMON]

E2E_CASES = [
    # (criterion id, test name, minimum, maximum) on the fixture-08-shaped corpus
    ("C1", "test_rejects_seven_characters", 0.3, 1.0),
    ("C1", "test_accepts_eight_characters", 0.3, 1.0),
    ("C1", "test_rejects_missing_digit", 0.0, 0.0),
    ("C1", "test_uppercase_rule_runs", 0.0, 0.0),
    ("C2", "test_rejects_missing_digit", 0.3, 1.0),
    ("C2", "test_rejects_seven_characters", 0.0, 0.0),
    ("C2", "test_accepts_eight_characters", 0.0, 0.0),
    ("C3", "test_uppercase_rule_runs", 0.3, 1.0),
    ("C3", "test_rejects_missing_digit", 0.0, 0.0),
    ("C4", "test_rejects_seven_characters", 0.0, 0.0),
    ("C4", "test_accepts_eight_characters", 0.0, 0.0),
    ("C4", "test_rejects_missing_digit", 0.0, 0.0),
    ("C4", "test_uppercase_rule_runs", 0.0, 0.0),
    ("C4", "test_is_blank", 0.0, 0.0),
    ("C1", "test_is_blank", 0.0, 0.0),
]


@pytest.fixture(scope="module")
def rel08():
    return run(F08_CRIT, F08)


@pytest.mark.parametrize("cid,name,lo,hi", E2E_CASES)
def test_fixture_08_shape(rel08, cid, name, lo, hi):
    r = rel08.r_ct(cid, f"tests/test_v.py::{name}")
    assert lo <= r <= hi, (cid, name, r)


def test_untested_criterion_gets_no_credit_from_unrelated_tests(rel08):
    assert [i.r_ct for i in rel08.for_criterion("C4")] == [0.0] * len(F08)
    assert relevant_tests(rel08, "C4") == []


def test_zero_has_no_signal_reason(rel08):
    item = rel08.get("C4", "tests/test_v.py::test_rejects_missing_digit")
    assert item and item.r_ct == 0.0
    assert [r.code for r in item.reasons] == ["no_signal"]


def test_weak_tests_do_not_support_error_criterion():
    c2 = C("C2", "an address without '@' raises ValueError")
    docs = [
        T(
            "test_normalize_returns_something",
            A("normalize_email(' Ann ')", "", "truthiness", ("normalize_email",)),
        ),
        T(
            "test_normalize_handles_plain_address",
            A("normalize_email('bob')", "None", "none_check", ("normalize_email",)),
        ),
    ]
    rel = run([c2], docs, "src/emails.py::normalize_email")
    assert relevant_tests(rel, "C2") == []


def test_exception_test_supports_error_criterion():
    c = C("C2", "percent outside 0..100 raises ValueError")
    good = T(
        "test_rejects_negative",
        A(
            "apply_discount(10, -1)",
            "ValueError",
            "exception",
            ("apply_discount",),
            "ValueError",
        ),
    )
    bad = T(
        "test_rounds",
        A("apply_discount(10, 5)", "9.5", "equality", ("apply_discount",)),
    )
    rel = run([c], [good, bad], "src/p.py::apply_discount")
    assert rel.r_ct("C2", good.test_id) > 0.9
    assert rel.r_ct("C2", bad.test_id) < 0.3


def test_wrong_exception_type_is_penalised():
    c = C("C2", "raises OutOfStock when qty exceeds stock")
    wrong = T(
        "test_reserve_bad_qty",
        A("reserve(1, 0)", "ValueError", "exception", ("reserve",), "ValueError"),
    )
    right = T(
        "test_reserve_too_much",
        A("reserve(1, 9)", "OutOfStock", "exception", ("reserve",), "OutOfStock"),
    )
    rel = run([c], [wrong, right], "src/s.py::reserve")
    assert rel.r_ct("C2", right.test_id) > 0.8
    assert rel.r_ct("C2", wrong.test_id) < 0.3
    assert "exception_type_mismatch" in [
        r.code for r in rel.get("C2", wrong.test_id).reasons
    ]


def test_behavior_mismatch_error_criterion_non_error_test():
    c = C("C2", "raises ValueError for empty input")
    t = T("test_empty_input_handled", A("f('')", "1", "equality", ("f",)))
    item = run([c], [t], "src/m.py::f").get("C2", t.test_id)
    assert "behavior_mismatch" in [r.code for r in item.reasons]


def test_success_criterion_vs_error_test_is_penalised_not_constraint():
    c = C("C1", "returns the price reduced by percent")
    err = T(
        "test_price_rejects_negative",
        A("f(-1)", "ValueError", "exception", ("f",), "ValueError"),
    )
    ok = T("test_price_reduced", A("f(5)", "4", "equality", ("f",)))
    rel = run([c], [err, ok], "src/m.py::f")
    assert rel.r_ct("C1", ok.test_id) > rel.r_ct("C1", err.test_id)
    assert "behavior_mismatch" in [r.code for r in rel.get("C1", err.test_id).reasons]


def test_constraint_criterion_keeps_rejecting_tests():
    c = C("C1", "a password needs at least 8 characters")
    t = T("test_rejects_seven_characters", A("v('abc')", "False", "equality", ("v",)))
    item = run([c], [t], "src/m.py::v").get("C1", t.test_id)
    assert "behavior_mismatch" not in [r.code for r in item.reasons]


def test_asserting_other_symbols_is_penalised():
    c = C("C1", "a password needs at least 8 characters")
    other = T(
        "test_accepts_eight_characters",
        A("is_blank('x')", "False", "equality", ("is_blank",)),
    )
    same = T(
        "test_accepts_eight_characters",
        A("validate_password('x')", "True", "equality", ("validate_password",)),
        path="tests/b.py",
    )
    rel = run([c], [other, same])
    assert rel.r_ct("C1", same.test_id) > rel.r_ct("C1", other.test_id)
    assert "asserts_other_symbols" in [
        r.code for r in rel.get("C1", other.test_id).reasons
    ]


def test_other_symbols_not_applied_without_symbol_names():
    c = C("C1", "a password needs at least 8 characters")
    t = T("test_accepts_eight_characters", A("x", "True", "truthiness"))
    assert "asserts_other_symbols" not in [
        r.code for r in run([c], [t]).get("C1", t.test_id).reasons
    ]


def test_subject_text_mention_avoids_other_symbol_penalty():
    c = C("C1", "a password needs at least 8 characters")
    t = T(
        "test_accepts_eight_characters",
        A("validate_password('x') and helper()", "True", "equality", ("helper",)),
    )
    assert "asserts_other_symbols" not in [
        r.code for r in run([c], [t]).get("C1", t.test_id).reasons
    ]


def test_hint_gives_one_and_beats_penalties():
    c = C(
        "C4",
        "a password must not be on the common-password list",
        tests=["test_is_blank"],
    )
    rel = run([c], F08)
    item = rel.get("C4", "tests/test_v.py::test_is_blank")
    assert item.r_ct == 1.0 and [r.code for r in item.reasons] == ["explicit_hint"]
    assert rel.r_ct("C4", "tests/test_v.py::test_uppercase_rule_runs") == 0.0


def test_hint_for_unconnected_test_creates_edge():
    c = C("C1", "anything at all", tests=["tests/other.py"])
    docs = [T("test_a", path="tests/other.py"), T("test_b", path="tests/x.py")]
    rel = score_relevance([c], docs, {})
    assert [(i.test_id, i.r_ct) for i in rel.items] == [("tests/other.py::test_a", 1.0)]
    assert rel.items[0].symbol_ids == ()


def test_unconnected_unhinted_pairs_are_not_scored():
    rel = score_relevance([DIGIT], F08, {})
    assert rel.items == ()


def test_unknown_ids_in_connections_ignored():
    rel = score_relevance(
        [DIGIT], F08, {("ZZ", F08[0].test_id): (SYM,), ("C2", "nope"): (SYM,)}
    )
    assert rel.items == ()


def test_specificity_penalty_applies_to_broad_tests():
    crits = [C(f"C{i}", "password digit uppercase length rule") for i in range(5)]
    broad = T("test_password_digit_uppercase_length_rule", VP())
    rel = run(crits, [broad, T("test_zzz", VP())])
    items = [rel.get(c.criterion_id, broad.test_id) for c in crits]
    assert all("specificity_penalty" in [r.code for r in i.reasons] for i in items)
    solo = run(crits[:1], [broad, T("test_zzz", VP())]).get("C0", broad.test_id)
    assert solo.r_ct > items[0].r_ct
    assert items[0].r_ct >= solo.r_ct * 0.5 - 1e-6


def test_specificity_not_applied_to_two_criteria():
    crits = [C("C1", "password digit rule"), C("C2", "password digit rule again")]
    t = T("test_digit_rule", VP())
    rel = run(crits, [t, T("test_zzz", VP())])
    assert all(
        "specificity_penalty" not in [r.code for r in i.reasons] for i in rel.items
    )


def test_below_floor_is_exactly_zero():
    cfg = RelevanceConfig(r_floor=0.9)
    rel = run([LENGTH], F08, cfg=cfg)
    for i in rel.items:
        assert i.r_ct == 0.0 or i.r_ct >= 0.9
    assert any("below_floor" in [r.code for r in i.reasons] for i in rel.items)


def test_gate_zero_when_no_signal_even_if_connected():
    t = T("test_zzz_qqq", A("v(1)", "9", "equality", ("validate_password",)))
    item = run([C("C1", "unrelated words entirely")], [t]).items[0]
    assert item.r_ct == 0.0


def test_signal_floor_blocks_weak_signal():
    cfg = RelevanceConfig(signal_floor=0.99)
    rel = run([LENGTH], F08, cfg=cfg)
    assert all(i.r_ct == 0.0 for i in rel.items)


def test_negative_factors_only_lower_scores():
    base = RelevanceConfig(
        behavior_mismatch_factor=1.0,
        success_mismatch_factor=1.0,
        exception_type_factor=1.0,
        other_symbols_factor=1.0,
        specificity_min=1.0,
    )
    crits = F08_CRIT
    a = run(crits, F08, cfg=base)
    b = run(crits, F08)
    for x, y in zip(a.items, b.items, strict=True):
        assert (x.criterion_id, x.test_id) == (y.criterion_id, y.test_id)
        assert y.r_ct <= x.r_ct + 1e-9


def test_monotone_in_signal_weights():
    lo = run(F08_CRIT, F08, cfg=RelevanceConfig(w_lexical=0.3, w_name=0.3))
    hi = run(F08_CRIT, F08, cfg=RelevanceConfig(w_lexical=0.9, w_name=0.9))
    for x, y in zip(lo.items, hi.items, strict=True):
        assert y.r_ct >= x.r_ct - 1e-9


def test_r_ct_always_in_unit_interval():
    rnd = random.Random(7)
    words = "password digit upper length reject raise error value none empty status 404 100 ok".split()
    for _ in range(25):
        crits = [C(f"C{i}", " ".join(rnd.choices(words, k=4))) for i in range(3)]
        docs = [
            T(
                "test_" + "_".join(rnd.choices(words, k=2)) + str(j),
                A(
                    " ".join(rnd.choices(words, k=2)),
                    rnd.choice(words),
                    rnd.choice(["equality", "exception"]),
                    exc=rnd.choice(["", "ValueError"]),
                ),
            )
            for j in range(4)
        ]
        for i in run(crits, docs).items:
            assert 0.0 <= i.r_ct <= 1.0


# --------------------------------------------------------------------------- determinism / io


def test_order_independent_and_ranked():
    r1 = run(F08_CRIT, F08)
    r2 = run(list(reversed(F08_CRIT)), list(reversed(F08)))
    assert r1.to_json() == r2.to_json()
    for cid in ("C1", "C2", "C3", "C4"):
        items = r1.for_criterion(cid)
        assert [i.rank for i in items] == list(range(1, len(items) + 1))
        assert [i.r_ct for i in items] == sorted((i.r_ct for i in items), reverse=True)


def test_ties_break_on_test_id():
    rel = run([C("C4", "zzz")], [T("test_b"), T("test_a")])
    assert [i.test_id.split("::")[1] for i in rel.items] == ["test_a", "test_b"]


def test_json_roundtrip_exact():
    rel = run(F08_CRIT, F08)
    again = RelevanceSet.from_json(rel.to_json())
    assert again.to_json() == rel.to_json()
    assert again.items == rel.items
    json.loads(rel.to_json())
    assert rel.config["algo_version"] == "criterion-test-relevance-v1"
    assert rel.config["signal_floor"] == 0.1


def test_get_and_r_ct_defaults():
    rel = run([LENGTH], F08)
    assert rel.get("C9", "x") is None and rel.r_ct("C9", "x") == 0.0


def test_relevant_tests_threshold():
    rel = run(F08_CRIT, F08)
    assert relevant_tests(rel, "C2") == ["tests/test_v.py::test_rejects_missing_digit"]
    assert relevant_tests(rel, "C2", 0.99) == []


# --------------------------------------------------------------------------- connections / adapters


def _link(cid, sid, score=0.8, linker=COMBINED):
    return Link(cid, sid, linker, score)


def _edge(sid, tid, score=0.9, linker=COMBINED):
    return SymbolTestEdge(sid, tid, score, linker=linker)


CONN_CASES = [
    (
        [_link("C1", "S1")],
        [_edge("S1", "t1"), _edge("S1", "t2")],
        {("C1", "t1"): ("S1",), ("C1", "t2"): ("S1",)},
    ),
    ([_link("C1", "S1")], [_edge("S2", "t1")], {}),
    ([_link("C1", "S1", linker="lexical")], [_edge("S1", "t1")], {}),
    ([_link("C1", "S1")], [_edge("S1", "t1", linker="naming")], {}),
    (
        [_link("C1", "S1"), _link("C1", "S2")],
        [_edge("S1", "t"), _edge("S2", "t")],
        {("C1", "t"): ("S1", "S2")},
    ),
    ([_link("C1", "S1", 0.0)], [_edge("S1", "t1")], {}),
    ([_link("C1", "S1")], [_edge("S1", "t1", 0.0)], {}),
]


@pytest.mark.parametrize("c2s,s2t,expected", CONN_CASES)
def test_connected_pairs(c2s, s2t, expected):
    assert connected_pairs(c2s, s2t) == expected


def test_connected_pairs_thresholds_and_order():
    c2s = [_link("C1", "S1", 0.2), _link("C2", "S1", 0.9)]
    s2t = [_edge("S1", "t1", 0.5)]
    assert list(connected_pairs(c2s, s2t, min_c2s=0.5)) == [("C2", "t1")]
    assert connected_pairs(c2s, s2t, min_s2t=0.6) == {}
    assert connected_pairs(c2s, s2t) == connected_pairs(reversed(c2s), s2t)


def test_relevance_from_links_end_to_end():
    d = T("test_rejects_missing_digit", VP())
    rel = relevance_from_links(
        [DIGIT, LENGTH],
        [d],
        [_link("C2", SYM), _link("C1", SYM)],
        [_edge(SYM, d.test_id)],
    )
    assert rel.r_ct("C2", d.test_id) >= 0.3
    assert rel.r_ct("C1", d.test_id) == 0.0
    assert rel.get("C2", d.test_id).symbol_ids == (SYM,)


ADAPT_CASES = [
    (
        {
            "kind": "exception",
            "subject": {"text": "f(1)", "refs": [{"name": "f"}, {"name": ""}]},
            "expected": {"text": "ValueError", "form": "exception_type"},
        },
        AssertionFact("f(1)", "ValueError", "exception", ("f",), "ValueError"),
    ),
    (
        {
            "kind": "equality",
            "subject": {"text": "x", "refs": []},
            "expected": {"text": "1", "form": "literal"},
        },
        AssertionFact("x", "1", "equality", (), ""),
    ),
    ({"kind": "truthiness"}, AssertionFact("", "", "truthiness", (), "")),
    (
        {
            "kind": "equality",
            "subject": {"text": "y"},
            "expected": {"text": "Err", "form": "exception_type"},
        },
        AssertionFact("y", "Err", "equality", (), "Err"),
    ),
]


@pytest.mark.parametrize("data,expected", ADAPT_CASES)
def test_from_assertion_dict(data, expected):
    assert AssertionFact.from_assertion_dict(data) == expected


def test_assertion_fact_flags_and_dict():
    f = AssertionFact("a", "b", "exception", ["n"], "E")
    assert f.is_exception and f.to_dict()["symbol_names"] == ["n"]
    assert not AssertionFact("a", "b", "equality").is_exception
    assert AssertionFact("a", kind="x", exception_type="E").is_exception


# --------------------------------------------------------------------------- domain validation

BAD_VALUES = [-0.1, 1.1, float("nan")]


@pytest.mark.parametrize("v", BAD_VALUES)
def test_reason_rejects_bad_value(v):
    with pytest.raises(ValueError):
        RelevanceReason("x", "d", v)


@pytest.mark.parametrize("v", BAD_VALUES)
def test_relevance_rejects_bad_score(v):
    with pytest.raises(ValueError):
        CriterionTestRelevance("C", "t", v)


def test_relevance_rounds_and_roundtrips():
    r = CriterionTestRelevance(
        "C", "t", 0.123456789, (RelevanceReason("a", "d", 0.5),), ["s"], 2
    )
    assert r.r_ct == 0.123457 and r.symbol_ids == ("s",)
    assert CriterionTestRelevance.from_dict(r.to_dict()) == r


BAD_CFG = [
    dict(signal_floor=-0.1),
    dict(r_floor=1.5),
    dict(w_lexical=2.0),
    dict(lexical_scale=0.0),
    dict(specificity_slope=-1.0),
    dict(specificity_free=-1),
    dict(other_symbols_factor=1.1),
]


@pytest.mark.parametrize("kw", BAD_CFG)
def test_config_validation(kw):
    with pytest.raises(ValueError):
        RelevanceConfig(**kw)


def test_config_to_dict_has_all_constants():
    d = RelevanceConfig().to_dict()
    assert d["w_assertion"] == 0.9 and d["specificity_min"] == 0.5 and len(d) == 17


def test_testdoc_normalises_sequences():
    d = TestDoc("i", "n", param_ids=["a"], assertions=[A()], literals=["x"])
    assert (
        d.param_ids == ("a",)
        and isinstance(d.assertions, tuple)
        and d.literals == ("x",)
    )


def test_domain_has_no_forbidden_imports():
    import ast
    from pathlib import Path

    import radius_linking

    for rel in ("domain/relevance.py", "application/relevance.py"):
        tree = ast.parse(
            (Path(radius_linking.__file__).parent / rel).read_text(encoding="utf-8")
        )
        roots = {
            (n.module or "").split(".")[0]
            if isinstance(n, ast.ImportFrom)
            else a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (n.names if isinstance(n, ast.Import) else [None])
        }
        assert not roots & {
            "radius_testing",
            "radius_evidence",
            "radius_analysis",
            "radius_graph",
        }
