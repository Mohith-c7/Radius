"""Validate the intent-to-evidence golden fixtures (F-14).

* every ``expected.json`` conforms to ``expected.schema.json``;
* cross-references inside it are consistent;
* the claimed test outcomes (base, head, head+probes, mutants) are re-executed
  with real pytest runs in isolated temp directories and must match;
* ``pr.patch`` equals the regenerated base-to-head diff.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_LOADER_PATH = Path(__file__).parent / "fixtures" / "intent" / "loader.py"
_spec = importlib.util.spec_from_file_location("intent_fixture_loader", _LOADER_PATH)
loader = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = loader
_spec.loader.exec_module(loader)

FIXTURES = loader.discover()
IDS = [fx.id for fx in FIXTURES]
SCHEMA = loader.load_schema()

REQUIRED_SCENARIOS = {
    "correct_strong_tests",
    "correct_weak_tests",
    "incorrect_passes_weak_tests",
    "test_tampering",
    "scope_creep",
    "hallucinated_dependency",
    "vague_intent",
    "multi_criterion_partial_evidence",
}


def test_all_required_scenarios_present_once():
    scenarios = [fx.expected["scenario"] for fx in FIXTURES]
    assert sorted(scenarios) == sorted(REQUIRED_SCENARIOS)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_expected_json_matches_schema(fixture):
    assert loader.validate_schema(fixture.expected, SCHEMA) == []
    assert fixture.expected["id"] == fixture.id


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_expected_json_is_internally_consistent(fixture):
    assert loader.check_consistency(fixture) == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_pr_patch_is_in_sync(fixture):
    committed = (fixture.path / "pr.patch").read_bytes().decode().replace("\r\n", "\n")
    assert committed == fixture.patch_text()
    assert committed.strip(), "patch must not be empty"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_claimed_test_outcomes_are_real(fixture):
    assert loader.verify_outcomes(fixture) == []


def test_tampering_fixture_goes_green_but_probes_fail():
    fx = next(f for f in FIXTURES if f.expected["scenario"] == "test_tampering")
    outcomes = fx.expected["test_outcomes"]
    assert "failed" not in outcomes["head"].values()
    assert "failed" in outcomes["head_with_probes"].values()
    assert {f["rule"] for f in fx.expected["tamper_findings"]} == {
        "T001", "T002", "T004", "T005"
    }


def test_incorrect_pr_passes_shipped_tests_but_fails_strong_probe():
    fx = next(f for f in FIXTURES if f.expected["scenario"] == "incorrect_passes_weak_tests")
    assert fx.expected["ground_truth"]["pr_correct"] is False
    assert set(fx.expected["test_outcomes"]["head"].values()) == {"passed"}
    assert "failed" in fx.expected["test_outcomes"]["head_with_probes"].values()
    assert fx.expected["expected_verdict"] != "verified"


def test_verifier_detects_a_false_claim():
    """Negative control: a wrong claim must be reported, not silently accepted."""
    fx = next(f for f in FIXTURES if f.expected["scenario"] == "incorrect_passes_weak_tests")
    bad = copy.deepcopy(fx.expected)
    probe = "tests/test_limits_strong.py::test_probe_clamp_below_returns_lo"
    bad["test_outcomes"]["head_with_probes"][probe] = "passed"
    errors = loader.verify_outcomes(replace(fx, expected=bad))
    assert any("head_with_probes" in e for e in errors)


def test_schema_rejects_malformed_expected():
    fx = FIXTURES[0]
    broken = json.loads(json.dumps(fx.expected))
    broken["expected_verdict"] = "looks_fine"
    broken["tamper_findings"] = [{"rule": "T999", "file": "x", "assumed_severity": "high", "detail": "d"}]
    del broken["criteria"]
    errors = loader.validate_schema(broken, SCHEMA)
    assert len(errors) >= 3


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_harness_kwargs_shape(fixture):
    kwargs = loader.harness_kwargs(fixture)
    assert set(kwargs) == {"name", "base", "change", "delete", "expect_full_suite_fails"}
    assert kwargs["change"], "head must differ from base"
    assert all(rel in fixture.base for rel in kwargs["delete"])
