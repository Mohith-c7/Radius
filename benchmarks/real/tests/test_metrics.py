"""Unit tests for benchmark metric aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrics import aggregate, classify_miss, prf, wilson  # noqa: E402


def _row(truth, conv_sel, conv_fail, rad_sel, rad_fail, verdict, total=10):
    return {"truth_failing": truth, "total_test_files": total,
            "full": {"selected": [], "failing": truth, "seconds": 2.0},
            "convention": {"selected": conv_sel, "failing": conv_fail, "seconds": 0.5},
            "radius": {"selected": rad_sel, "failing": rad_fail, "verdict": verdict, "seconds": 1.0}}


def test_wilson_known_values() -> None:
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def test_prf() -> None:
    assert prf({"a", "b"}, {"a"}) == (0.5, 1.0)
    assert prf(set(), {"a"}) == (None, 0.0)
    assert prf({"a"}, set()) == (0.0, None)


def test_aggregate_detection_false_safe_abstention() -> None:
    rows = [
        _row(["t1"], ["t1"], ["t1"], ["t1", "t2"], ["t1"], "failed"),
        _row(["t3"], [], [], ["t1"], [], "verified"),             # radius false-safe
        _row(["t4"], ["t4"], ["t4"], ["t4"], [], "insufficient_evidence"),
        _row([], ["t9"], [], ["t9"], [], "verified"),             # undetected mutant
    ]
    conv = aggregate(rows, "convention")
    assert (conv["detected"], conv["caught"], conv["missed"]) == (3, 2, 1)
    rad = aggregate(rows, "radius")
    assert (rad["caught"], rad["missed"]) == (1, 2)
    assert rad["false_safe"] == 1  # undetected 'verified' is not counted
    assert rad["abstain"] == 1
    assert rad["recall"] == pytest.approx((1 + 0 + 1) / 3)
    assert rad["precision"] == pytest.approx((0.5 + 0 + 1) / 3)
    assert rad["fraction"] == pytest.approx((2 + 1 + 1 + 1) / 40)
    assert rad["seconds"] == 1.0


def test_classify_miss() -> None:
    assert classify_miss(_row(["t1"], [], [], ["t1"], ["t1"], "failed"), "radius") is None
    assert classify_miss(_row(["t1"], [], [], ["t2"], [], "verified"), "radius") == "selection error"
    assert classify_miss(_row(["t1"], ["t1"], [], [], [], "verified"), "convention") == "isolation/environment"
    assert classify_miss(_row(["t1"], [], [], [], [], "insufficient_evidence"), "radius") == "selection error (abstained)"
    assert classify_miss(_row([], [], [], [], [], "verified"), "radius") is None
