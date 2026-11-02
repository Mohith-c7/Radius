"""Gold-mode reproduction of the design's worked numbers (VERDICT_V2_SLICE 7.3).

Inputs follow design 7.3: links from each fixture's ``expected.json``, l_cs = 1,
l_st = 0.9, r_ct = 1, tests added in the PR with unknown author (i = 0.8),
``a_static`` from the test bodies. Chain under test: ``evidence_quality_row``
-> ``compute_support`` -> ``evaluate_criterion`` -> ``compute_uim``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.enums import (
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    Flag,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.inputs import (
    CriterionInput,
    CriterionSymbolEdgeInput,
    SymbolInput,
)
from radius_evidence.domain.model import (
    EvidenceItem,
    FlakyInfo,
    FreshnessInfo,
    IndependenceInfo,
)
from radius_evidence.domain.quality import evidence_quality_row
from radius_evidence.domain.states import (
    compute_uim,
    evaluate_criterion,
    intent_coverage,
)
from radius_evidence.domain.support import compute_support

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
EXPECT = json.loads(
    (
        ROOT / "docs" / "research" / "design" / "verdict_v2.fixture_expectations.json"
    ).read_text(encoding="utf-8")
)
TOL = EXPECT["tolerance"]
SHA = "b" * 40
CFG = VerdictV2Config()

# a_static by assertion kind in the fixture tests (design 7.2).
EQ, RAISES, TRUTHY, BOUND, TYPE, TAUT = 1.0, 0.8, 0.25, 0.35, 0.2, 0.0

#: fixture -> criterion -> list of (test name, a_static, tamper severities)
TESTS: dict[str, dict[str, list[tuple[str, float, tuple[str, ...]]]]] = {
    "01_correct_strong_tests": {
        "C1": [
            ("reduces_price", EQ, ()),
            ("zero_identity", EQ, ()),
            ("hundred_free", EQ, ()),
            ("rounds_cents", EQ, ()),
        ],
        "C2": [("rejects_negative", RAISES, ()), ("rejects_above_100", RAISES, ())],
    },
    "02_correct_weak_tests": {
        "C1": [("returns_something", TRUTHY, ()), ("plain_address", TRUTHY, ())],
        "C2": [],
    },
    "03_incorrect_passes_weak_tests": {
        "C1": [("above_bounded", BOUND, ())],
        "C2": [("returns_int", TYPE, ())],
        "C3": [("inside_in_range", BOUND, ())],
    },
    "04_test_tampering": {
        # T004 (high) hits the weak test, the other is x == x; the raises test
        # for C3 carries a high finding; the C2 test was deleted (T001): no item.
        "C1": [("reduces_stock", TRUTHY, ("high",)), ("exact_stock", TAUT, ())],
        "C2": [],
        "C3": [("rejects_non_positive", RAISES, ("high",))],
    },
    "05_scope_creep": {
        "C1": [("basic", EQ, ()), ("underscore", EQ, ())],
        "C2": [("basic2", EQ, ()), ("collapses", EQ, ()), ("empty", EQ, ())],
    },
    "06_hallucinated_dependency": {
        "C1": [
            ("hours_minutes", EQ, ()),
            ("seconds_only", EQ, ()),
            ("with_spaces", EQ, ()),
        ],
        "C2": [("rejects_garbage", RAISES, ()), ("rejects_empty", RAISES, ())],
    },
    "07_vague_intent": {"C1": [], "C2": []},
    "08_multi_criterion_partial_evidence": {
        "C1": [("rejects_seven", EQ, ()), ("accepts_eight", EQ, ())],
        "C2": [("rejects_missing_digit", EQ, ())],
        "C3": [("uppercase_runs", TYPE, ())],
        "C4": [],
    },
}
TESTABILITY = {
    ("07_vague_intent", "C1"): "vague",
    ("07_vague_intent", "C2"): "non_functional",
}
#: (symbol id, path, kind, pseudo) of behavioral changed symbols; the covering
#: criterion edges are given by ``COVERED``.
SYMBOLS = {
    "05_scope_creep": [
        ("slugify", "src/text_utils.py", "function", False),
        ("round_money", "src/billing.py", "function", False),
        ("config_module", "src/config.py", "module", True),
    ],
}
COVERED = {"05_scope_creep": {"C1": "slugify", "C2": "slugify"}}


def _item(eid: str, name: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=eid,
        kind=EvidenceKind.TEST_OUTCOME,
        source=EvidenceSource.CI_UPLOAD,
        analysis_id="a",
        repository_id="r",
        head_sha=SHA,
        subject_id=f"tests/t.py::{name}",
        path="tests/t.py",
        symbol_ids=("sym",),
        criterion_ids=(),
        outcome=Outcome.PASSED,
        duration_ms=1,
        features=None,
        severity=None,
        rule_id=None,
        independence=IndependenceInfo(
            AuthoredBy.UNKNOWN, IndependenceBasis.CHANGED_IN_PR, 0.8
        ),
        flaky=FlakyInfo(False),
        freshness=FreshnessInfo(SHA, SHA, 1.0, "current_head"),
        reasons=(),
        collected_at="2026-11-02T10:00:00Z",
    )


def run(fixture: str):
    results = {}
    supports = {}
    criteria = []
    for cid, tests in TESTS[fixture].items():
        rows = [
            evidence_quality_row(
                _item(f"{cid}:{name}", name),
                cid,
                a_static=a,
                w_cs=1.0,
                w_st=0.9,
                r_ct=1.0,
                symbol_id="sym",
                tamper_severities=sev,
                quality=CFG.quality,
                mapping=CFG.link,
            )
            for name, a, sev in tests
        ]
        c = CriterionInput(
            cid, "t", 1.0, TESTABILITY.get((fixture, cid), "testable"), "confirmed"
        )
        sup = compute_support(cid, rows, CFG.support)
        criteria.append(c)
        supports[cid] = sup
        results[cid] = evaluate_criterion(c, sup, CFG, n_addressed_tests=len(tests))
    active = [
        c.criterion_id
        for c in criteria
        if results[c.criterion_id].state.value != "excluded"
    ]
    symbols = [
        SymbolInput(s, p, s, k, "python", "modified", True, False, ps)
        for s, p, k, ps in SYMBOLS.get(fixture, [])
    ]
    edges = [
        CriterionSymbolEdgeInput(c, s, 0.9, 1)
        for c, s in COVERED.get(fixture, {}).items()
    ]
    cov = intent_coverage(symbols, edges, active, CFG.link.link_min_cs)
    return criteria, supports, results, compute_uim(criteria, results, cov, CFG), cov


FIXTURES = [f["fixture"] for f in EXPECT["fixtures"]]
BY_NAME = {f["fixture"]: f for f in EXPECT["fixtures"]}


def test_every_expectation_fixture_has_inputs() -> None:
    assert set(FIXTURES) == set(TESTS)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_gold_states_s_and_uim_match_the_design(fixture: str) -> None:
    gold = BY_NAME[fixture]["gold"]
    _, supports, results, uim, _ = run(fixture)
    for cid, want in gold["states"].items():
        assert results[cid].state.value == want, (fixture, cid)
    for cid, want in gold["S"].items():
        if gold["states"][cid] != "excluded":
            assert supports[cid].S == pytest.approx(want, abs=TOL), (fixture, cid)
    assert uim.uim == pytest.approx(gold["uim"], abs=TOL)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_intent_coverage_matches_the_design(fixture: str) -> None:
    assert run(fixture)[4] == pytest.approx(
        BY_NAME[fixture]["intent_coverage"], abs=TOL
    )


def test_fixture_04_is_flagged_tampered() -> None:
    _, _, results, _, _ = run("04_test_tampering")
    assert Flag.TAMPERED in results["C1"].flags and Flag.TAMPERED in results["C3"].flags
    assert Flag.TAMPERED not in results["C2"].flags


def test_fixture_07_reason_flags() -> None:
    _, _, results, uim, _ = run("07_vague_intent")
    assert results["C1"].reasons[0].code == "not_testable"
    assert Flag.NEEDS_TYPED_EVIDENCE in results["C2"].flags
    assert uim.excluded_criterion_ids == ("C1",) and uim.uim == 1.0


def test_fixture_08_c4_has_no_linked_test_flag() -> None:
    _, _, results, _, _ = run("08_multi_criterion_partial_evidence")
    assert Flag.NO_LINKED_TEST in results["C4"].flags


def test_known_design_disagreement_08_c2_is_weak_under_alpha_static() -> None:
    # expected.json says proven; one static-only test cannot reach tau_support 0.5.
    _, supports, results, _, _ = run("08_multi_criterion_partial_evidence")
    assert supports["C2"].S == pytest.approx(0.432, abs=TOL)
    assert results["C2"].state.value == "weak"
