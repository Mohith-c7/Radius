"""EV-06/EV-01 on the 8 F-14 fixtures: a_static ranks the fixture tests like expected.json."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from radius_evidence.application.normalize import normalize_evidence
from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    StageAInput,
    StageBInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.strength import a_static


def _load_helper():  # no cross-module package import: `tests` collides with apps/api/tests
    path = Path(__file__).with_name("fixture_features.py")
    spec = importlib.util.spec_from_file_location("evidence_fixture_features", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_helper = _load_helper()
ROOT, all_features, fixture_dirs = (
    _helper.ROOT,
    _helper.all_features,
    _helper.fixture_dirs,
)

SHA = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
EXPECT = json.loads(
    (ROOT / "benchmarks/fixtures/verdict_v2/fixture_expectations.json").read_text(
        "utf-8"
    )
)
DIRS = fixture_dirs()
IDS = [d.name for d in DIRS]


def _expected(d):
    return json.loads((d / "expected.json").read_text("utf-8"))


def test_eight_fixtures() -> None:
    assert len(DIRS) == 8


@pytest.mark.parametrize("fixture", DIRS, ids=IDS)
def test_bands_rank_like_expected_json(fixture) -> None:
    feats = all_features(fixture)
    checked = 0
    for entry in _expected(fixture)["evidence_quality"]:
        test_id = entry["test"]
        if test_id not in feats:  # deleted at head (fixture 04): no evidence at all
            assert entry["band"] == "none"
            continue
        score = a_static(feats[test_id])
        band = entry["band"]
        if band == "strong":
            assert score >= 0.8, (test_id, score)
        elif band == "weak":
            assert 0.0 < score <= 0.4, (test_id, score)
        elif feats[test_id].has_skip_marker:
            assert "skipped" in entry["rationale"]  # skipped: outcome SKIPPED zeroes q
        elif (
            "different function" not in entry["rationale"]
            and "unrelated" not in entry["rationale"]
        ):
            assert score <= 0.25, (test_id, score, entry["rationale"])
        checked += 1
    assert checked > 0


def test_strong_beats_weak_beats_none_in_fixture_08() -> None:
    feats = all_features(next(d for d in DIRS if d.name.startswith("08")))
    strong = a_static(feats["tests/test_validators.py::test_rejects_missing_digit"])
    weak = a_static(feats["tests/test_validators.py::test_uppercase_rule_runs"])
    assert strong > weak > 0.0
    assert strong * 0.6 == pytest.approx(0.6)  # capped by cap_static later (EV-08)


def test_fixture_04_tautology_and_skip() -> None:
    feats = all_features(next(d for d in DIRS if d.name.startswith("04")))
    assert a_static(feats["tests/test_stock.py::test_reserve_exact_stock"]) == 0.0
    assert feats[
        "tests/test_stock.py::test_reserve_rejects_non_positive"
    ].has_skip_marker
    assert feats[
        "tests/test_stock.py::test_reserve_rejects_non_positive"
    ].expects_exception


@pytest.mark.parametrize("fixture", DIRS, ids=IDS)
def test_normalizing_head_outcomes(fixture) -> None:
    exp = _expected(fixture)
    feats = all_features(fixture)
    head = exp["test_outcomes"]["head"]
    cases = tuple(
        CaseOutcomeInput(None, tid.split("::")[0], None, tid, Outcome(o))
        for tid, o in head.items()
    )
    findings = tuple(
        TamperFindingInput(
            f"tf_{i}",
            f["rule"],
            f.get("detail", ""),
            f["assumed_severity"],
            1.0,
            f["file"],
        )
        for i, f in enumerate(exp["tamper_findings"])
    )
    sa = StageAInput(
        analysis_id=fixture.name,
        repository_id="r",
        head_sha=SHA,
        changeset_ref="c",
        criteria=(),
        symbols=(),
        criterion_symbol=(),
        symbol_test=tuple(
            SymbolTestEdgeInput("s", t, 0.9, "direct_call") for t in feats
        ),
        criterion_test=(),
        assertions=tuple(feats.values()),
        tamper=findings,
    )
    res = normalize_evidence(
        StageBInput(sa, cases=cases, results_received=True),
        collected_at="2026-11-02T10:00:00Z",
    )
    assert res.rejected == ()
    tests = {i.subject_id: i for i in res.items if i.outcome is not None}
    assert set(head) <= set(tests)
    for tid, outcome in head.items():
        assert tests[tid].outcome is Outcome(outcome), tid
    assert len([i for i in res.items if i.severity]) == len(findings)
    expected_tamper = next(
        e for e in EXPECT["fixtures"] if e["fixture"] == fixture.name
    ).get("expected_tamper", [])
    assert len(expected_tamper) == len(exp["tamper_findings"]) or not expected_tamper
