"""scripts/test_link_eval.py: pure helpers and a full fixture run with a canned ground truth."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "test_link_eval.py"
FIXTURE = Path(__file__).resolve().parents[3] / "benchmarks" / "fixtures" / "intent" / "01_correct_strong_tests"

pytestmark = pytest.mark.skipif(not FIXTURE.is_dir(), reason="intent fixtures not present")


@pytest.fixture(scope="module")
def tle():
    spec = importlib.util.spec_from_file_location("test_link_eval_script_mod", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _CannedTruth:
    """Stand-in for the sandboxed tracer: every discount test executes apply_discount."""

    def trace(self, repo, files):
        from radius_testing.linking.coveragedb import CoverageData

        names = [
            "test_discount_reduces_price", "test_discount_zero_is_identity", "test_discount_hundred_is_free",
            "test_discount_rounds_to_cents", "test_discount_rejects_negative_percent",
            "test_discount_rejects_percent_above_hundred",
        ]  # fmt: skip
        return CoverageData({f"tests/test_pricing.py::{n}": {"src/pricing.py": frozenset({9, 10})} for n in names})


def test_changed_targets_exclude_test_files(tle):
    targets = tle.changed_targets(FIXTURE / "base", FIXTURE / "head", (FIXTURE / "pr.patch").read_text())
    assert [t.qualified_name for t in targets] == ["apply_discount"]


def test_evaluate_fixture_with_canned_truth(tle):
    result = tle.evaluate_fixture(FIXTURE, _CannedTruth(), None, 0.3)
    rows = result["variants"]
    assert set(rows) == {"static", "naming", "static+naming"}
    assert rows["static"]["vs_dynamic_truth"]["recall"] == 1.0
    assert rows["static"]["vs_labelled"]["precision"] == 1.0
    assert rows["naming"]["vs_dynamic_truth"]["recall"] < 1.0
    json.dumps(result)


def test_aggregate_and_table(tle):
    result = tle.evaluate_fixture(FIXTURE, _CannedTruth(), None, 0.3)
    agg = tle.aggregate([result, result], "vs_dynamic_truth")
    assert agg["static"]["tp"] == 2 * result["variants"]["static"]["vs_dynamic_truth"]["tp"]
    table = tle.format_table("title", agg)
    assert "static+naming" in table and "precision" in table


def test_truth_requires_sandbox_or_explicit_opt_in(tle, tmp_path):
    with pytest.raises(RuntimeError, match="host-trusted"):
        tle.Truth(None, False).trace(tmp_path, [])


def test_expected_labels_map_to_symbol_ids(tle):
    from radius_testing.linking import LinkTarget

    expected = json.loads((FIXTURE / "expected.json").read_text())
    target = LinkTarget("python:src/pricing.py::apply_discount#function@h", "src/pricing.py", "apply_discount")
    labels = tle.expected_labels(expected, [target])
    assert target.symbol_id in labels and "tests/test_pricing.py::test_discount_reduces_price" in labels[target.symbol_id]
