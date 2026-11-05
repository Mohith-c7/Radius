# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Calibrators, reliability metrics and artifacts (LK-06). Hand-computed expectations."""

from __future__ import annotations

import json
import math
import random
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import pytest

from chain_helpers import edge, link
from radius_linking.application import build_support_links
from radius_linking.domain import (
    BinningCalibrator,
    CalibrationArtifact,
    CalibrationError,
    IsotonicCalibrator,
    PlattCalibrator,
    SupportLinkSet,
    brier_score,
    expected_calibration_error,
    fit_artifact,
    maximum_calibration_error,
    reliability_bins,
    reliability_report,
)
from radius_linking.domain.calibration import pav


# ------------------------------------------------------------------- metrics
def test_ece_mce_brier_hand_case():
    s, y = [0.1, 0.1, 0.9, 0.9], [0, 0, 1, 0]
    assert expected_calibration_error(s, y) == pytest.approx(0.5 * 0.1 + 0.5 * 0.4)
    assert maximum_calibration_error(s, y) == pytest.approx(0.4)
    assert brier_score(s, y) == pytest.approx((0.01 + 0.01 + 0.01 + 0.81) / 4)


def test_perfect_and_worst_calibration():
    assert expected_calibration_error([0.5, 0.5], [1, 0]) == pytest.approx(0.0)
    assert expected_calibration_error([1.0, 1.0], [0, 0]) == pytest.approx(1.0)
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_reliability_bins_edges_and_report():
    bins = reliability_bins([0.0, 0.1, 0.1, 1.0], [0, 1, 0, 1], n_bins=10)
    assert [(b.low, b.count) for b in bins] == [(0.0, 1), (0.1, 2), (0.9, 1)]
    assert bins[1].positive_rate == 0.5 and bins[2].mean_score == 1.0
    rep = reliability_report([0.2, 0.8], [0, 1], n_bins=5)
    assert rep["n"] == 2 and rep["n_positive"] == 1
    assert rep["ece"] == pytest.approx(0.2)
    json.dumps(rep)


@pytest.mark.parametrize(
    "scores,labels",
    [([], []), ([0.5], [1, 0]), ([1.2], [1]), ([0.5], [2]), ([float("nan")], [1])],
)
def test_metrics_reject_bad_input(scores, labels):
    with pytest.raises(CalibrationError):
        brier_score(scores, labels)


def test_bins_reject_zero_bins():
    with pytest.raises(CalibrationError):
        reliability_bins([0.5], [1], 0)


# ----------------------------------------------------------------------- PAV
def test_pav_hand_values():
    assert pav([1, 3, 2, 4, 3, 5], [1] * 6) == pytest.approx([1, 2.5, 2.5, 3.5, 3.5, 5])
    assert pav([3, 2, 1], [1, 1, 1]) == pytest.approx([2, 2, 2])
    assert pav([1, 2, 3], [1, 1, 1]) == [1, 2, 3]
    assert pav([2, 0], [1, 3]) == pytest.approx([0.5, 0.5])  # (2*1 + 0*3) / 4


def test_isotonic_matches_pav_reference_example():
    # PAV of [0,1,0,1,1,0] is [0, .5, .5, 2/3, 2/3, 2/3] (same as scikit-learn)
    xs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    cal = IsotonicCalibrator().fit(xs, [0, 1, 0, 1, 1, 0])
    got = [cal.transform(x) for x in xs]
    assert got == pytest.approx([0, 0.5, 0.5, 2 / 3, 2 / 3, 2 / 3])
    assert cal.transform(0.25) == pytest.approx(0.5)
    assert cal.transform(0.35) == pytest.approx(0.5 + 0.5 * (2 / 3 - 0.5))
    assert cal.transform(0.0) == 0.0
    assert cal.transform(1.0) == pytest.approx(2 / 3)


def test_isotonic_ties_are_pooled():
    cal = IsotonicCalibrator().fit([0.5, 0.5, 0.5, 0.9], [1, 0, 0, 1])
    assert cal.transform(0.5) == pytest.approx(1 / 3)
    assert cal.transform(0.9) == 1.0
    assert cal.transform(0.7) == pytest.approx((1 / 3 + 1.0) / 2)


def test_isotonic_random_is_monotone_and_not_worse_in_brier():
    rng = random.Random(1)
    s = [rng.random() for _ in range(300)]
    y = [1 if rng.random() < x**2 else 0 for x in s]
    cal = IsotonicCalibrator().fit(s, y)
    vals = [cal.transform(i / 100) for i in range(101)]
    assert vals == sorted(vals) and vals[0] >= 0 and vals[-1] <= 1
    assert brier_score([cal.transform(x) for x in s], y) <= brier_score(s, y)


def test_isotonic_single_point_and_unfitted():
    cal = IsotonicCalibrator().fit([0.4], [1])
    assert cal.transform(0.0) == 1.0 == cal.transform(1.0)
    with pytest.raises(CalibrationError):
        IsotonicCalibrator().transform(0.5)
    with pytest.raises(CalibrationError):
        IsotonicCalibrator().params()


# ------------------------------------------------------------------- binning
def test_binning_hand_values_and_empty_bins():
    cal = BinningCalibrator(10).fit([0.05, 0.15, 0.15, 0.95], [0, 1, 0, 1])
    assert cal.transform(0.0) == 0.0
    assert cal.transform(0.1) == 0.5
    assert cal.transform(0.5) == 0.5  # empty bin takes the previous non-empty bin
    assert cal.transform(1.0) == 1.0 and cal.transform(0.96) == 1.0


def test_binning_leading_empty_bins_use_next():
    cal = BinningCalibrator(4).fit([0.9, 0.95], [1, 0])
    assert cal.transform(0.0) == 0.5


def test_binning_validation_and_unfitted():
    with pytest.raises(CalibrationError):
        BinningCalibrator(0)
    with pytest.raises(CalibrationError):
        BinningCalibrator().transform(0.3)
    with pytest.raises(CalibrationError):
        BinningCalibrator().params()
    with pytest.raises(CalibrationError):
        BinningCalibrator.from_params({"n_bins": 2, "values": [0.1]})


# --------------------------------------------------------------------- Platt
def platt_grad(cal, s, y):
    """Gradient of the Platt-smoothed NLL at the fitted (A, B): ~0 at the optimum."""
    n_pos = sum(y)
    n_neg = len(y) - n_pos
    hi, lo = (n_pos + 1) / (n_pos + 2), 1 / (n_neg + 2)
    ga = gb = 0.0
    for x, yi in zip(s, y, strict=True):
        t = hi if yi else lo
        p = 1 / (1 + math.exp(cal.a * x + cal.b))
        ga += x * (t - p)
        gb += t - p
    return ga, gb


def test_platt_separable_data_is_finite_and_monotone():
    s = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
    y = [0, 0, 0, 1, 1, 1]
    cal = PlattCalibrator().fit(s, y)
    assert math.isfinite(cal.a) and math.isfinite(cal.b)
    assert cal.a < 0  # p = 1 / (1 + exp(A s + B)) increases with the score
    assert cal.transform(0.1) < 0.5 < cal.transform(0.9)
    assert cal.transform(0.5) == pytest.approx(0.5, abs=0.05)
    ga, gb = platt_grad(cal, s, y)
    assert abs(ga) < 1e-6 and abs(gb) < 1e-6


def test_platt_non_separable_stationary_point():
    rng = random.Random(3)
    s = [rng.random() for _ in range(200)]
    y = [1 if rng.random() < 0.2 + 0.6 * x else 0 for x in s]
    cal = PlattCalibrator().fit(s, y)
    ga, gb = platt_grad(cal, s, y)
    assert abs(ga) < 1e-6 and abs(gb) < 1e-6
    vals = [cal.transform(i / 20) for i in range(21)]
    assert vals == sorted(vals)
    assert expected_calibration_error([cal.transform(x) for x in s], y) < 0.1


def test_platt_constant_score_reduces_to_smoothed_base_rate():
    cal = PlattCalibrator().fit([0.5] * 10, [1] * 3 + [0] * 7)
    expect = (3 * (4 / 5) + 7 * (1 / 9)) / 10  # mean of the smoothed targets
    assert cal.transform(0.5) == pytest.approx(expect, abs=1e-6)


def test_platt_needs_both_classes_and_is_deterministic():
    with pytest.raises(CalibrationError):
        PlattCalibrator().fit([0.2, 0.4], [1, 1])
    with pytest.raises(CalibrationError):
        PlattCalibrator().transform(0.5)
    with pytest.raises(CalibrationError):
        PlattCalibrator().params()
    a = PlattCalibrator().fit([0.1, 0.4, 0.6, 0.9], [0, 1, 0, 1]).params()
    b = PlattCalibrator().fit([0.1, 0.4, 0.6, 0.9], [0, 1, 0, 1]).params()
    assert a == b


def test_platt_extreme_parameters_do_not_overflow():
    cal = PlattCalibrator.from_params({"A": -800.0, "B": 400.0})
    assert cal.transform(0.0) == pytest.approx(0.0, abs=1e-12)
    assert cal.transform(1.0) == pytest.approx(1.0)
    with pytest.raises(CalibrationError):
        PlattCalibrator.from_params({"A": float("inf"), "B": 0})


# ------------------------------------------------------------------ artifacts
DATA_S = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
DATA_Y = [0, 0, 0, 1, 0, 1, 1, 0, 1, 1]


@pytest.mark.parametrize("method", ["binning", "platt", "isotonic"])
def test_artifact_round_trip(method):
    art = fit_artifact(
        method, DATA_S, DATA_Y, dataset_id="toy", source_algo_version="link-chain-v1"
    )
    again = CalibrationArtifact.from_json(art.to_json())
    assert again == art and again.artifact_id == art.artifact_id
    for s in (0.0, 0.33, 0.5, 0.99, 1.0):
        want = art.calibrator().transform(s)
        assert again.calibrator().transform(s) == pytest.approx(want)
    assert art.fit["n"] == 10 and art.fit["in_sample"] is True
    assert art.fit["dataset_id"] == "toy"
    assert art.version == "link-calibration-v1"


def test_fit_metrics_recorded_and_extra_merged():
    art = fit_artifact("isotonic", DATA_S, DATA_Y, extra={"split": "dev"})
    assert art.fit["split"] == "dev"
    assert art.fit["brier_after"] <= art.fit["brier_before"]


def test_artifact_rejects_tampering_and_bad_versions():
    art = fit_artifact("platt", DATA_S, DATA_Y).to_dict()

    def tamper(d):
        d["params"]["A"] += 1

    for mutate in (
        tamper,
        lambda d: d.update(version="v0"),
        lambda d: d.update(method="magic"),
        lambda d: d.update(target="nope"),
        lambda d: d.pop("checksum"),
    ):
        d = json.loads(json.dumps(art))
        mutate(d)
        with pytest.raises(CalibrationError):
            CalibrationArtifact.from_dict(d)
    with pytest.raises(CalibrationError):
        CalibrationArtifact.from_json("{not json")
    with pytest.raises(CalibrationError):
        CalibrationArtifact.from_json("{}")


def test_fit_artifact_validation():
    with pytest.raises(CalibrationError):
        fit_artifact("magic", DATA_S, DATA_Y)
    with pytest.raises(CalibrationError):
        fit_artifact("platt", DATA_S, DATA_Y, target="nope")


def test_invalid_isotonic_params_rejected():
    with pytest.raises(CalibrationError):
        IsotonicCalibrator.from_params({"x": [0.5, 0.1], "y": [0.1, 0.2]})
    with pytest.raises(CalibrationError):
        IsotonicCalibrator.from_params({"x": [0.1, 0.5], "y": [0.5, 0.2]})


# ------------------------------------------------ applied only when supplied
def _one(**kw):
    return build_support_links(
        ["C1", "C2"], [link("C1", "S1", a=0.8)], [edge("S1", "T1", b=0.9)], **kw
    )


def test_default_is_uncalibrated():
    res = _one()
    assert res.score_kind == "link_confidence_uncalibrated" and res.calibration is None
    assert res.criteria[0].link_confidence == pytest.approx(0.72)


def test_criterion_calibration_applied_when_supplied():
    art = fit_artifact("isotonic", DATA_S, DATA_Y, target="criterion")
    res = _one(criterion_calibration=art)
    c1, c2 = res.criteria
    assert res.score_kind == "link_confidence_calibrated"
    assert c1.score_kind == "link_confidence_calibrated"
    assert c1.raw_link_confidence == pytest.approx(0.72)
    want = art.calibrator().transform(0.72)
    assert c1.link_confidence == pytest.approx(want, abs=1e-6)
    assert any(r.kind == "calibrated" for r in c1.reasons)
    assert c2.link_confidence == 0.0
    assert any(r.kind == "unlinked_not_calibrated" for r in c2.reasons)
    assert res.calibration["criterion"]["artifact_id"] == art.artifact_id
    assert c1.chains[0].chain_score == pytest.approx(0.72)  # no chain artifact given


def test_chain_calibration_keeps_raw_and_criterion_untouched():
    art = fit_artifact("platt", DATA_S, DATA_Y, target="chain")
    res = _one(chain_calibration=art)
    ch = res.criteria[0].chains[0]
    assert ch.score_kind == "link_confidence_calibrated"
    assert ch.raw_chain_score == pytest.approx(0.72)
    assert ch.chain_score == pytest.approx(art.calibrator().transform(0.72), abs=1e-6)
    assert res.score_kind == "link_confidence_uncalibrated"
    assert res.criteria[0].link_confidence == pytest.approx(0.72)


def test_wrong_target_artifact_refused():
    chain_art = fit_artifact("platt", DATA_S, DATA_Y, target="chain")
    crit_art = fit_artifact("platt", DATA_S, DATA_Y, target="criterion")
    with pytest.raises(CalibrationError):
        _one(criterion_calibration=chain_art)
    with pytest.raises(CalibrationError):
        _one(chain_calibration=crit_art)


def test_calibrated_set_round_trips():
    res = _one(criterion_calibration=fit_artifact("binning", DATA_S, DATA_Y))
    assert SupportLinkSet.from_json(res.to_json()) == res
