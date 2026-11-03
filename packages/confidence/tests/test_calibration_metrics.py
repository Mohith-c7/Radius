"""Calibration metrics checked against hand-computed values (no fitted data, no results)."""

from __future__ import annotations

import math
import random

import pytest
from radius_confidence.calibration import (
    brier_decomposition,
    brier_score,
    ece,
    expected_calibration_error,
    log_loss,
    max_calibration_error,
    reliability_bins,
    reliability_curve,
)
from radius_confidence.calibration._validate import CalibrationInputError

# Four items: two at 0.1 (labels 0, 1), two at 0.9 (labels 1, 1).
S = [0.1, 0.1, 0.9, 0.9]
Y = [0, 1, 1, 1]


def test_hand_computed_ece_brier_logloss():
    # bin 0.1: n=2, mean conf 0.1, observed 0.5, gap 0.4; bin 0.9: n=2, gap 0.1
    assert ece(S, Y, 10, "width") == pytest.approx((2 * 0.4 + 2 * 0.1) / 4)
    assert ece(S, Y, 2, "mass") == pytest.approx(0.25)
    # (0.01 + 0.81 + 0.01 + 0.01) / 4
    assert brier_score(S, Y) == pytest.approx(0.21)
    assert log_loss(S, Y) == pytest.approx(-(3 * math.log(0.9) + math.log(0.1)) / 4)
    bins = reliability_bins(S, Y, 10, "width")
    assert max_calibration_error(bins) == pytest.approx(0.4)
    assert expected_calibration_error(bins) == pytest.approx(0.25)


def test_equal_width_edges_and_score_one():
    bins = reliability_bins([0.0, 0.05, 0.1, 1.0], [0, 0, 1, 1], 10, "width")
    assert [b.count for b in bins] == [2, 1, 0, 0, 0, 0, 0, 0, 0, 1]
    assert bins[2].mean_confidence is None and bins[2].gap is None
    assert bins[0].lower == 0.0 and bins[9].upper == 1.0


def test_equal_mass_sizes_differ_by_at_most_one_and_are_deterministic():
    rng = random.Random(3)
    scores = [rng.random() for _ in range(103)]
    labels = [rng.randrange(2) for _ in scores]
    sizes = [b.count for b in reliability_bins(scores, labels, 10, "mass")]
    assert sum(sizes) == 103 and max(sizes) - min(sizes) <= 1
    assert sizes == [11, 11, 11, 10, 10, 10, 10, 10, 10, 10]
    assert reliability_bins(scores, labels, 10, "mass") == reliability_bins(scores, labels, 10, "mass")


def test_equal_mass_with_fewer_items_than_bins():
    bins = reliability_bins([0.2, 0.8], [0, 1], 10, "mass")
    assert [b.count for b in bins] == [1, 1]


def test_perfectly_calibrated_bins_have_zero_ece():
    scores = [0.25] * 4 + [0.75] * 4
    labels = [1, 0, 0, 0] + [1, 1, 1, 0]
    assert ece(scores, labels, 10, "width") == pytest.approx(0.0)


def test_log_loss_clips_extremes():
    v = log_loss([0.0, 1.0], [1, 0])
    assert math.isfinite(v) and v == pytest.approx(-math.log(1e-15), abs=0.01)


def test_brier_decomposition_identity_holds():
    rng = random.Random(11)
    scores = [rng.random() for _ in range(400)]
    labels = [int(rng.random() < s) for s in scores]
    for strategy in ("width", "mass"):
        d = brier_decomposition(scores, labels, 10, strategy)
        assert d.brier == pytest.approx(
            d.reliability - d.resolution + d.uncertainty + d.within_bin, abs=1e-12
        )
        assert d.brier == pytest.approx(brier_score(scores, labels))


def test_brier_decomposition_exact_when_bins_hold_one_score():
    d = brier_decomposition(S, Y, 10, "width")
    assert d.within_bin == pytest.approx(0.0)
    assert d.reliability == pytest.approx((2 * 0.4**2 + 2 * 0.1**2) / 4)
    assert d.uncertainty == pytest.approx(0.75 * 0.25)


def test_reliability_curve_has_only_nonempty_bins_and_is_plot_ready():
    curve = reliability_curve(S, Y, 10, "width")
    assert [round(p["mean_confidence"], 3) for p in curve] == [0.1, 0.9]
    assert [p["observed_frequency"] for p in curve] == [0.5, 1.0]
    assert all({"lower", "upper", "count"} <= set(p) for p in curve)


@pytest.mark.parametrize(
    "scores, labels",
    [([0.5], [0, 1]), ([1.2], [1]), ([float("nan")], [1]), ([0.5], [2]), ([], [])],
)
def test_invalid_input_is_rejected(scores, labels):
    with pytest.raises(CalibrationInputError):
        brier_score(scores, labels)


def test_unknown_strategy_and_bad_bin_count():
    with pytest.raises(CalibrationInputError):
        reliability_bins(S, Y, 10, "nope")  # type: ignore[arg-type]
    with pytest.raises(CalibrationInputError):
        reliability_bins(S, Y, 0)


def test_ece_noise_floor_is_positive_for_calibrated_simulation():
    """Seeded sanity check of the noise-floor premise (PREREGISTRATION 7.5).

    Data drawn from a perfectly calibrated model still has ECE well above 0 at
    small N and smaller at larger N. Not a reproduction of any specific figure.
    """

    def mean_ece(n: int) -> float:
        rng = random.Random(7)
        total = 0.0
        for _ in range(60):
            s = [rng.betavariate(1.2, 2.8) for _ in range(n)]
            y = [int(rng.random() < p) for p in s]
            total += ece(s, y, 10, "mass")
        return total / 60

    small, large = mean_ece(250), mean_ece(2000)
    assert small > 0.02 and small > large
