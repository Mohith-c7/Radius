"""The fixture expectations file matches the 8 F-14 fixtures (names, criteria ids).

VS-02 reads ``benchmarks/fixtures/verdict_v2/fixture_expectations.json``; this
test keeps it structurally honest and identical to the design copy.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from radius_evidence.domain.enums import SupportState

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
EXPECTATIONS = ROOT / "benchmarks" / "fixtures" / "verdict_v2" / "fixture_expectations.json"
DESIGN_COPY = ROOT / "docs" / "research" / "design" / "verdict_v2.fixture_expectations.json"
FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
VERDICTS = {"verified", "failed", "insufficient_evidence", "needs_review"}
STATES = {s.value for s in SupportState}
RULES = {"R1a", "R1b", "R1c", "R2p", "R2a", "R2b", "R2c", "R2d", "R3a", "R3b", "R3c", "R4"}


def _load() -> dict:
    return json.loads(EXPECTATIONS.read_text(encoding="utf-8"))


def test_wired_copy_equals_the_design_file() -> None:
    assert _load() == json.loads(DESIGN_COPY.read_text(encoding="utf-8"))


def test_covers_exactly_the_eight_f14_fixtures() -> None:
    names = {p.name for p in FIXTURES.iterdir() if (p / "expected.json").is_file()}
    assert len(names) == 8
    assert {f["fixture"] for f in _load()["fixtures"]} == names
    assert len(_load()["fixtures"]) == 8


def test_each_entry_matches_its_fixture_criteria() -> None:
    data = _load()
    assert data["profile"] == "alpha-static"
    for entry in data["fixtures"]:
        expected = json.loads(
            (FIXTURES / entry["fixture"] / "expected.json").read_text(encoding="utf-8")
        )
        criteria = {c["id"] for c in expected["criteria"]}
        assert entry["expected_verdict"] in VERDICTS, entry["fixture"]
        decided = set(re.findall(r"R\d[a-z]?", entry["decided_by"]))
        assert decided and decided <= RULES, entry["fixture"]
        assert 0.0 <= entry["intent_coverage"] <= 1.0
        for mode in ("gold", "auto"):
            block = entry[mode]
            assert set(block["states"]) == criteria, (entry["fixture"], mode)
            assert set(block["states"].values()) <= STATES
            assert set(block["S"]) <= criteria if "S" in block else True
            assert 0.0 <= block["uim"] <= 1.0
