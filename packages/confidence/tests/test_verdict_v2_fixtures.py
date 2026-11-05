"""The 8 F-14 fixtures reach the expected PR verdicts (VD-03 acceptance).

Inputs are hand-built per-criterion results (state and S from
``verdict_v2.fixture_expectations.json``; gold-link numbers from the design).
This tests the rules in isolation from linking quality (design 7.3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from radius_confidence.verdict_v2.application.service import compute_verdict_v2
from radius_confidence.verdict_v2.domain.model import CriterionVerdict, Verdict
from radius_confidence.verdict_v2.domain.rules import AnalysisFacts
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.enums import SupportState
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.states import UimResult

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
DESIGN = ROOT / "docs" / "research" / "design"
EXPECT = json.loads((DESIGN / "verdict_v2.fixture_expectations.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((DESIGN / "verdict_v2.example.08.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((DESIGN / "verdict_v2.schema.json").read_text(encoding="utf-8"))
TAU = 0.5
HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"

#: fixture number -> overrides of the generic construction.
TESTABILITY = {
    ("07", "C1"): "subjective_or_vague",
    ("07", "C2"): "non_functional_measurable",
}
#: Behavioral symbols changed per fixture (|B| of design 3.9); 05 has 3 (1 covered).
BEHAVIORAL = {"05": 3}
DECIDED = {("05", "gold"): "R2c", ("05", "auto"): "R2b"}


def _tamper(fixture: dict[str, Any], severity: str | None = None) -> tuple[TamperFindingInput, ...]:
    return tuple(
        TamperFindingInput(
            finding_id=f"tf_{t['rule_id']}_{n}",
            rule_id=t["rule_id"],
            check="x",
            severity=severity or t["severity"],
            confidence=0.9,
            path="tests/test_x.py",
        )
        for n, t in enumerate(fixture.get("expected_tamper", []))
    )


def _criteria(num: str, mode: dict[str, Any]) -> list[CriterionVerdict]:
    rows = []
    for cid, state in mode["states"].items():
        s = mode["S"][cid]
        rows.append(
            CriterionVerdict(
                criterion_id=cid,
                text=f"criterion {cid}",
                weight=1.0,
                testability=TESTABILITY.get((num, cid), "behavioral_testable"),
                lifecycle="confirmed",
                state=SupportState(state),
                S=s,
                S_raw=s,
            )
        )
    return rows


def _uim(criteria: list[CriterionVerdict], coverage: float) -> UimResult:
    live = [c for c in criteria if c.state != SupportState.EXCLUDED]
    unproven = [c for c in live if c.S < TAU]
    den = float(len(live))
    return UimResult(
        uim=len(unproven) / den if den else 0.0,
        numerator=float(len(unproven)),
        denominator=den,
        intent_coverage=coverage,
        unproven_criterion_ids=tuple(c.criterion_id for c in unproven),
    )


def _compute(fixture: dict[str, Any], mode_name: str, tamper: tuple[TamperFindingInput, ...] | None = None):
    num = fixture["fixture"][:2]
    criteria = _criteria(num, fixture[mode_name])
    coverage = fixture["intent_coverage"]
    # Scope creep: the gold mode differs from auto only in S; coverage is the same.
    uim = _uim(criteria, coverage)
    return (
        compute_verdict_v2(
            analysis_id=fixture["fixture"],
            head_sha=HEAD,
            revision=1,
            criteria=criteria,
            uim=uim,
            facts=AnalysisFacts(
                results_received=True,
                tamper=_tamper(fixture) if tamper is None else tamper,
                behavioral_symbols=BEHAVIORAL.get(num, 1),
            ),
        ),
        uim,
    )


CASES = [(f, m) for f in EXPECT["fixtures"] for m in ("gold", "auto")]
IDS = [f"{f['fixture'][:2]}-{m}" for f, m in CASES]


@pytest.mark.parametrize(("fixture", "mode"), CASES, ids=IDS)
def test_fixture_verdict_matches_expectation(fixture: dict[str, Any], mode: str) -> None:
    verdict, uim = _compute(fixture, mode)
    assert verdict.verdict == Verdict(fixture["expected_verdict"])
    num = fixture["fixture"][:2]
    expected_rule = DECIDED.get((num, mode))
    if expected_rule is None:
        expected_rule = fixture["decided_by"]
    assert verdict.justification["decided_by"] == expected_rule
    assert uim.uim == pytest.approx(fixture[mode]["uim"], abs=EXPECT["tolerance"])
    assert verdict.pending is False


@pytest.mark.parametrize(("fixture", "mode"), CASES, ids=IDS)
def test_fixture_tree_is_schema_valid_and_reproducible(fixture: dict[str, Any], mode: str) -> None:
    verdict, _ = _compute(fixture, mode)
    assert validate(verdict.justification, SCHEMA["properties"]["justification"]) == []
    again, _ = _compute(fixture, mode)
    assert again.to_json() == verdict.to_json()
    assert [r["id"] for r in verdict.justification["rules"]][-1] == "R4"


def test_fixture_06_offline_registry_variant_needs_review() -> None:
    fixture = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("06"))
    variant = fixture["offline_registry_variant"]
    verdict, _ = _compute(fixture, "gold", tamper=_tamper(fixture, severity="medium"))
    assert verdict.verdict == Verdict(variant["expected_verdict"])
    assert verdict.justification["decided_by"] == variant["decided_by"]


def test_fixture_05_gold_is_decided_by_coverage_only() -> None:
    fixture = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("05"))
    verdict, _ = _compute(fixture, "gold")
    fired = [r["id"] for r in verdict.justification["rules"] if r["fired"]]
    assert fired == ["R2c"]
    assert verdict.intent_coverage == pytest.approx(0.333)


def test_fixture_05_auto_fires_unproven_mass_and_coverage() -> None:
    fixture = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("05"))
    verdict, _ = _compute(fixture, "auto")
    assert [r["id"] for r in verdict.justification["rules"] if r["fired"]] == ["R2b", "R2c"]


def test_fixture_04_fails_by_tamper_not_by_unproven_mass() -> None:
    fixture = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("04"))
    verdict, _ = _compute(fixture, "gold")
    assert verdict.verdict == Verdict.FAILED
    r1c = verdict.justification["rules"][2]
    assert r1c["fired"] and len(r1c["refs"]["finding_ids"]) == 4


def test_fixture_07_vague_intent_reason_code() -> None:
    fixture = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("07"))
    verdict, _ = _compute(fixture, "gold")
    assert verdict.reasons[0].code == fixture["reason_code"]


def test_fixture_01_is_the_only_verified_one() -> None:
    verdicts = {f["fixture"][:2]: _compute(f, "gold")[0].verdict for f in EXPECT["fixtures"]}
    assert [k for k, v in verdicts.items() if v == Verdict.VERIFIED] == ["01"]


def test_no_fixture_verdict_is_verified_for_the_wrong_pr() -> None:
    # 03 is an incorrect PR passing weak tests: never verified.
    f03 = next(f for f in EXPECT["fixtures"] if f["fixture"].startswith("03"))
    assert _compute(f03, "gold")[0].verdict != Verdict.VERIFIED


def test_fixture_08_matches_the_design_example_justification() -> None:
    criteria = [
        CriterionVerdict(
            criterion_id=c["criterion_id"],
            text=c["text"],
            weight=c["weight"],
            testability=c["testability"],
            lifecycle=c["lifecycle"],
            state=SupportState(c["state"]),
            S=c["S"],
            S_raw=c["S_raw"],
        )
        for c in EXAMPLE["criteria"]
    ]
    uim = _uim(criteria, 1.0)
    verdict = compute_verdict_v2(
        analysis_id=EXAMPLE["analysis_id"],
        head_sha=EXAMPLE["head_sha"],
        revision=EXAMPLE["revision"],
        criteria=criteria,
        uim=uim,
        facts=AnalysisFacts(results_received=True, behavioral_symbols=1),
        config=VerdictV2Config(),
    )
    ours = verdict.justification
    theirs = EXAMPLE["justification"]
    assert ours["decided_by"] == theirs["decided_by"] == "R2b"
    assert ours["verdict"] == theirs["verdict"]
    assert ours["thresholds"] == theirs["thresholds"]
    assert ours["versions"] == theirs["versions"]
    assert [(r["id"], r["label"], r["fired"]) for r in ours["rules"]] == [
        (r["id"], r["label"], r["fired"]) for r in theirs["rules"]
    ]
    ours_r2b = next(r for r in ours["rules"] if r["id"] == "R2b")
    theirs_r2b = next(r for r in theirs["rules"] if r["id"] == "R2b")
    assert ours_r2b["inputs"] == theirs_r2b["inputs"]
    assert ours_r2b["refs"]["criterion_ids"] == theirs_r2b["refs"]["criterion_ids"]
    assert verdict.reasons[0].detail == EXAMPLE["reasons"][0]["detail"]
    assert verdict.reasons[0].code == EXAMPLE["reasons"][0]["code"]


# ------------------------------------------------- tiny stdlib JSON-schema subset validator

def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        kinds = {
            "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
        }
        ok = False
        for n in names:
            if n == "number":
                ok |= isinstance(value, (int, float)) and not isinstance(value, bool)
            elif n == "integer":
                ok |= isinstance(value, int) and not isinstance(value, bool)
            else:
                ok |= isinstance(value, kinds[n])
        if not ok:
            return [*errors, f"{path}: bad type {type(value).__name__}"]
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: pattern")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        errors += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errors += validate(v, props[k], f"{path}.{k}")
            elif isinstance(extra, dict):
                errors += validate(v, extra, f"{path}.{k}")
            elif extra is False:
                errors.append(f"{path}: unexpected {k!r}")
    return errors
