"""Isotonic (PAV) and Platt calibrators, the identity prior and the sample-size guards."""

from __future__ import annotations

import random

import pytest
from radius_confidence.calibration import (
    CalibrationPolicy,
    CalibrationState,
    Calibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    UncalibratedPrior,
    brier_score,
    fit_calibrator,
)
from radius_confidence.calibration._validate import CalibrationInputError

POLICY = CalibrationPolicy(
    min_n_report=100, min_per_class=5, min_n_fit=50, isotonic_min_n=200, min_n_threshold=100
)


def _calibrated_sample(n: int, seed: int) -> tuple[list[float], list[int]]:
    rng = random.Random(seed)
    s = [rng.random() for _ in range(n)]
    return s, [int(rng.random() < p) for p in s]


def test_isotonic_hand_computed_pav():
    # [0, 1, 0, 1] at 0.1..0.4: the middle violators pool to 0.5
    iso = IsotonicCalibrator.fit([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    assert iso.xs == (0.1, 0.2, 0.3, 0.4)
    assert iso.ys == (0.0, 0.5, 0.5, 1.0)
    assert iso.calibrate(0.25).value == pytest.approx(0.5)
    assert iso.calibrate(0.15).value == pytest.approx(0.25)  # linear between anchors
    assert iso.calibrate(0.0).value == 0.0 and iso.calibrate(1.0).value == 1.0


def test_isotonic_pools_tied_scores_and_ignores_input_order():
    s = [0.5, 0.5, 0.5, 0.2, 0.9]
    y = [1, 0, 0, 0, 1]
    a = IsotonicCalibrator.fit(s, y)
    b = IsotonicCalibrator.fit(list(reversed(s)), list(reversed(y)))
    assert a.xs == b.xs and a.ys == b.ys
    assert a.calibrate(0.5).value == pytest.approx(1 / 3)


def test_isotonic_all_one_class_is_constant():
    iso = IsotonicCalibrator.fit([0.1, 0.5, 0.9], [1, 1, 1])
    assert all(iso.calibrate(x).value == 1.0 for x in (0.0, 0.4, 1.0))


@pytest.mark.parametrize("seed", range(8))
def test_isotonic_output_is_monotone_and_in_unit_interval(seed):
    rng = random.Random(seed)
    n = rng.randrange(5, 300)
    s = [round(rng.random(), rng.choice([1, 2, 6])) for _ in range(n)]  # many ties sometimes
    y = [rng.randrange(2) for _ in s]
    iso = IsotonicCalibrator.fit(s, y)
    grid = [i / 500 for i in range(501)]
    out = [iso.calibrate(x).value for x in grid]
    assert all(0.0 <= v <= 1.0 for v in out)
    assert all(b >= a - 1e-12 for a, b in zip(out, out[1:], strict=False))


def test_isotonic_preserves_mean_label_on_training_data():
    s, y = _calibrated_sample(300, 5)
    iso = IsotonicCalibrator.fit(s, y)
    mean_pred = sum(iso.calibrate(x).value for x in s) / len(s)
    # PAV with linear interpolation between block ends is not exactly mean preserving;
    # it must stay close to the base rate.
    assert abs(mean_pred - sum(y) / len(y)) < 0.03


def test_platt_recovers_identity_on_calibrated_data_and_is_monotone():
    s, y = _calibrated_sample(4000, 2)
    platt = PlattCalibrator.fit(s, y)
    assert platt.a == pytest.approx(1.0, abs=0.15)
    assert platt.b == pytest.approx(0.0, abs=0.15)
    out = [platt.calibrate(x).value for x in (0.05, 0.3, 0.5, 0.8, 0.95)]
    assert out == sorted(out)


def test_platt_reduces_brier_on_miscalibrated_scores():
    rng = random.Random(9)
    truth = [rng.random() for _ in range(3000)]
    y = [int(rng.random() < p) for p in truth]
    over = [min(1.0, max(0.0, 0.5 + 1.8 * (p - 0.5))) for p in truth]  # overconfident
    platt = PlattCalibrator.fit(over[:1500], y[:1500])
    before = brier_score(over[1500:], y[1500:])
    after = brier_score([c.value for c in platt.calibrate_many(over[1500:])], y[1500:])
    assert after < before


def test_platt_needs_both_classes_and_handles_separable_data():
    with pytest.raises(CalibrationInputError):
        PlattCalibrator.fit([0.1, 0.9], [1, 1])
    sep = PlattCalibrator.fit([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1])
    assert sep.a > 0
    assert 0.0 < sep.calibrate(0.05).value < sep.calibrate(0.95).value < 1.0


def test_platt_raw_feature_variant():
    platt = PlattCalibrator.fit([0.1, 0.2, 0.3, 0.7, 0.8, 0.9], [0, 0, 1, 0, 1, 1], feature="raw")
    assert platt.feature == "raw" and platt.a > 0
    with pytest.raises(CalibrationInputError):
        PlattCalibrator.fit([0.1, 0.9], [0, 1], feature="nope")


def test_uncalibrated_prior_is_identity_and_labelled():
    prior = UncalibratedPrior("test")
    c = prior.calibrate(0.37)
    assert c.value == 0.37 and c.state is CalibrationState.UNCALIBRATED_PRIOR
    with pytest.raises(CalibrationInputError):
        prior.calibrate(1.5)


def test_all_calibrators_satisfy_the_protocol():
    s, y = _calibrated_sample(300, 1)
    for cal in (UncalibratedPrior(), IsotonicCalibrator.fit(s, y), PlattCalibrator.fit(s, y)):
        assert isinstance(cal, Calibrator)
        assert cal.calibrate(0.5).state in set(CalibrationState)


# ------------------------------------------------------------------ guards


def test_fit_calibrator_refuses_below_declared_n():
    s, y = _calibrated_sample(40, 4)
    cal = fit_calibrator("auto", s, y, POLICY)
    assert isinstance(cal, UncalibratedPrior)
    assert "below the declared minimum 50" in cal.reason
    assert cal.calibrate(0.8).value == 0.8  # pass-through, never "more certain"


def test_fit_calibrator_refuses_when_a_class_is_too_small():
    s = [i / 100 for i in range(100)]
    y = [1] * 3 + [0] * 97
    cal = fit_calibrator("platt", s, y, POLICY)
    assert isinstance(cal, UncalibratedPrior) and "smallest class" in cal.reason


def test_auto_follows_the_isotonic_threshold_rule():
    s, y = _calibrated_sample(120, 6)
    assert isinstance(fit_calibrator("auto", s, y, POLICY), PlattCalibrator)
    s, y = _calibrated_sample(400, 6)
    assert isinstance(fit_calibrator("auto", s, y, POLICY), IsotonicCalibrator)
    # explicit isotonic below its threshold is refused, not silently downgraded
    s, y = _calibrated_sample(120, 6)
    refused = fit_calibrator("isotonic", s, y, POLICY)
    assert isinstance(refused, UncalibratedPrior) and "isotonic needs N >= 200" in refused.reason


def test_policy_requires_positive_integers():
    with pytest.raises(CalibrationInputError):
        CalibrationPolicy(0, 1, 1, 1, 1)
    with pytest.raises(TypeError):
        CalibrationPolicy()  # type: ignore[call-arg]
