"""Intervals (Clopper-Pearson, bootstrap), abstention thresholds and the report guard."""

from __future__ import annotations

import math
import random

import pytest
from radius_confidence.calibration import (
    CalibrationPolicy,
    bootstrap_ci,
    brier_score,
    clopper_pearson,
    clopper_pearson_lower,
    clopper_pearson_upper,
    crc_threshold,
    evaluate_calibration,
    evaluate_threshold,
    find_nonincreasing_violation,
    ltt_threshold,
    prereg_shifted_loss,
    risk_coverage_curve,
    select_threshold,
)
from radius_confidence.calibration._validate import CalibrationInputError
from radius_confidence.calibration.intervals import binomial_cdf, percentile


def _direct_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


# --------------------------------------------------------- Clopper-Pearson


@pytest.mark.parametrize("k, n, p", [(0, 5, 0.3), (3, 10, 0.3), (7, 20, 0.55), (49, 50, 0.9)])
def test_binomial_cdf_matches_direct_summation(k, n, p):
    assert binomial_cdf(k, n, p) == pytest.approx(_direct_cdf(k, n, p), abs=1e-12)


def test_clopper_pearson_closed_forms():
    assert clopper_pearson_upper(0, 10, 0.05) == pytest.approx(1 - 0.05 ** (1 / 10), abs=1e-9)
    assert clopper_pearson_lower(10, 10, 0.05) == pytest.approx(0.05 ** (1 / 10), abs=1e-9)
    assert clopper_pearson_upper(10, 10, 0.05) == 1.0
    assert clopper_pearson_lower(0, 10, 0.05) == 0.0
    assert clopper_pearson_upper(0, 0, 0.05) == 1.0  # no data, no information


def test_clopper_pearson_reference_value_3_of_10():
    lo, hi = clopper_pearson(3, 10, 0.95)
    assert lo == pytest.approx(0.0667, abs=5e-4)
    assert hi == pytest.approx(0.6525, abs=5e-4)


def test_clopper_pearson_exact_coverage_by_enumeration():
    n, p = 30, 0.3
    covered = 0.0
    for k in range(n + 1):
        lo, hi = clopper_pearson(k, n, 0.95)
        if lo <= p <= hi:
            covered += math.comb(n, k) * p**k * (1 - p) ** (n - k)
    assert covered >= 0.95  # exact intervals are conservative, never below nominal


def test_upper_bound_is_monotone_in_k_and_n():
    ubs = [clopper_pearson_upper(k, 40, 0.05) for k in range(0, 15)]
    assert ubs == sorted(ubs)
    assert clopper_pearson_upper(2, 400, 0.05) < clopper_pearson_upper(2, 40, 0.05)


# --------------------------------------------------------------- bootstrap


def _sample(n: int, seed: int) -> tuple[list[float], list[int]]:
    rng = random.Random(seed)
    s = [rng.random() for _ in range(n)]
    return s, [int(rng.random() < p) for p in s]


def test_percentile_linear_interpolation():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.0) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 1.0) == 4.0


def test_bootstrap_is_seeded_and_brackets_the_estimate():
    s, y = _sample(300, 1)
    a = bootstrap_ci(brier_score, s, y, seed=5, n_resamples=200)
    b = bootstrap_ci(brier_score, s, y, seed=5, n_resamples=200)
    c = bootstrap_ci(brier_score, s, y, seed=6, n_resamples=200)
    assert a == b and a != c
    assert a.lower <= a.estimate <= a.upper and a.n_valid == 200


def test_bootstrap_interval_narrows_with_more_data():
    w = []
    for n in (100, 1600):
        s, y = _sample(n, 2)
        ci = bootstrap_ci(brier_score, s, y, seed=1, n_resamples=200)
        w.append(ci.upper - ci.lower)
    assert w[1] < w[0] / 2


def test_cluster_bootstrap_resamples_whole_clusters():
    s = [0.1, 0.1, 0.9, 0.9]
    y = [0, 0, 1, 1]
    seen_sizes: set[int] = set()

    def stat(ss: list[float], yy: list[int]) -> float:
        seen_sizes.add(len(ss))
        return sum(yy) / len(yy)

    ci = bootstrap_ci(stat, s, y, seed=3, n_resamples=50, clusters=["a", "a", "b", "b"])
    assert ci.clustered and seen_sizes <= {4}
    with pytest.raises(CalibrationInputError):
        bootstrap_ci(stat, s, y, seed=3, clusters=["a"])


def test_bootstrap_drops_undefined_resamples():
    s, y = [0.2, 0.8], [0, 1]
    ci = bootstrap_ci(lambda ss, yy: None if len(set(yy)) < 2 else 1.0, s, y, seed=1, n_resamples=100)
    assert 0 < ci.n_valid < 100


# ----------------------------------------------------- risk-coverage curve


def test_risk_coverage_curve_hand_computed_with_ties():
    conf = [0.9, 0.9, 0.7, 0.5, 0.5]
    ok = [1, 0, 1, 1, 0]
    pts = risk_coverage_curve(conf, ok)
    assert [(p.threshold, p.n_accepted, p.n_errors) for p in pts] == [(0.9, 2, 1), (0.7, 3, 1), (0.5, 5, 2)]
    assert pts[0].risk == 0.5 and pts[-1].coverage == 1.0 and pts[-1].risk == pytest.approx(0.4)


def test_coverage_is_nondecreasing_along_the_curve():
    s, y = _sample(200, 3)
    cov = [p.coverage for p in risk_coverage_curve(s, y)]
    assert cov == sorted(cov)


def test_evaluate_threshold_reports_exact_upper_bound():
    out = evaluate_threshold([0.9] * 20 + [0.2] * 5, [1] * 19 + [0] + [0] * 5, 0.5, delta=0.05)
    assert (out["n_accepted"], out["n_errors"]) == (20, 1)
    assert out["error_upper_bound"] == pytest.approx(clopper_pearson_upper(1, 20, 0.05))
    none = evaluate_threshold([0.9], [1], None)
    assert none["n_accepted"] == 0 and none["error_upper_bound"] is None


# ------------------------------------------------------ threshold selection


def test_ltt_hand_cases():
    conf = [0.6] * 100
    d = ltt_threshold(conf, [1] * 100, alpha=0.1, delta=0.1, grid=[0.0, 0.5, 0.9])
    # k=0, n=100, delta/3: bound 1 - (0.1/3)^(1/100) ~ 0.0335 <= 0.1; lowest grid point 0.0
    assert d.threshold == 0.0 and d.n_accepted_cal == 100 and d.errors_cal == 0
    assert d.upper_bound == pytest.approx(1 - (0.1 / 3) ** (1 / 100), abs=1e-9)
    assert d.accepts(0.3) and not d.abstains_on_everything


def test_small_calibration_set_abstains_never_accepts_more():
    d = ltt_threshold([0.99] * 10, [1] * 10, alpha=0.1, delta=0.1, grid=[0.0])
    # k=0, n=10 at delta=0.1: bound 0.206 > 0.1, cannot be certified
    assert d.threshold is None and d.abstains_on_everything and not d.accepts(1.0)
    c = crc_threshold([0.99] * 8, [1] * 8, alpha=0.1)  # 1/(n+1) = 0.111 > alpha
    assert c.abstains_on_everything


def test_more_data_never_leads_to_a_lower_certified_bar_than_less_data_with_same_rates():
    lo_n = ltt_threshold([0.8] * 40 + [0.3] * 40, [1] * 40 + [0, 1] * 20, 0.1, 0.1, [0.0, 0.5])
    hi_n = ltt_threshold([0.8] * 400 + [0.3] * 400, [1] * 400 + [0, 1] * 200, 0.1, 0.1, [0.0, 0.5])
    assert hi_n.coverage_cal >= lo_n.coverage_cal


def test_crc_hand_case_threshold_is_smallest_qualifying_score():
    # n=9, no errors: 9/10 * 0 + 1/10 = 0.1 <= alpha=0.1 -> lowest score qualifies
    conf = [0.1 * i for i in range(1, 10)]
    d = crc_threshold(conf, [1] * 9, alpha=0.1)
    assert d.threshold == pytest.approx(0.1) and d.n_accepted_cal == 9
    # one error at the lowest score: accepting all gives 9/10 * 1/9 + 1/10 = 0.2 > 0.15,
    # dropping the lowest item (the error) gives 0.1 <= 0.15
    d2 = crc_threshold(conf, [0] + [1] * 8, alpha=0.15)
    assert d2.threshold == pytest.approx(0.2) and d2.errors_cal == 0


def test_ltt_selected_threshold_respects_alpha_with_probability_1_minus_delta():
    """Seeded simulation of the finite-sample statement (not a result).

    Scores uniform, P(correct | s) = s, so the true error among accepted at
    threshold t is (1 - t) / 2 and the guarantee can be checked exactly.
    """

    alpha, delta, reps, n = 0.2, 0.1, 80, 1000
    grid = [i / 20 for i in range(21)]
    rng = random.Random(20261102)
    violations = selected = 0
    for _ in range(reps):
        s = [rng.random() for _ in range(n)]
        y = [int(rng.random() < p) for p in s]
        d = ltt_threshold(s, y, alpha, delta, grid)
        if d.threshold is not None:
            selected += 1
            if (1 - d.threshold) / 2 > alpha:
                violations += 1
    assert selected > reps * 0.5  # not vacuous: usually certifies something
    assert violations / reps <= delta + 0.05  # slack for Monte Carlo noise


def test_crc_joint_risk_is_at_most_alpha_on_average():
    """Seeded simulation: E[P(accepted and incorrect)] <= alpha (CRC statement)."""

    alpha, reps, n = 0.1, 300, 200
    rng = random.Random(7)
    joint = []
    for _ in range(reps):
        s = [rng.random() for _ in range(n)]
        y = [int(rng.random() < p) for p in s]
        d = crc_threshold(s, y, alpha)
        joint.append(0.0 if d.threshold is None else (1 - d.threshold) ** 2 / 2)
    assert sum(joint) / reps <= alpha + 0.01


def test_prereg_shifted_loss_is_not_nonincreasing_in_the_threshold():
    """Documents the monotonicity gap flagged for CA-05 (PREREGISTRATION 7.1).

    A correct item accepted at a low threshold has loss -alpha; once the
    threshold passes its confidence the loss rises to 0. CRC needs non-increasing.
    """

    conf, ok, alpha = [0.8, 0.8, 0.3], [1, 0, 0], 0.1

    def shifted(i: int, t: float) -> float:
        return prereg_shifted_loss(conf[i], ok[i], t, alpha)

    def joint(i: int, t: float) -> float:
        return float((1 - ok[i]) * (conf[i] >= t))

    v = find_nonincreasing_violation(shifted, 3, [0.0, 0.5, 0.9])
    assert v is not None and v["item"] == 0
    assert v["loss_lo"] == pytest.approx(-0.1) and v["loss_hi"] == 0.0
    assert find_nonincreasing_violation(joint, 3, [0.0, 0.5, 0.9]) is None


# ------------------------------------------------------------------ guards

POLICY = CalibrationPolicy(
    min_n_report=200, min_per_class=20, min_n_fit=100, isotonic_min_n=500, min_n_threshold=200
)


def test_report_withheld_below_declared_n():
    s, y = _sample(150, 1)
    rep = evaluate_calibration(s, y, POLICY, seed=1, n_resamples=20)
    assert rep["state"] == "uncalibrated_prior" and rep["metrics"] is None
    assert any("below the declared minimum 200" in r for r in rep["reasons"])
    assert rep["n"] == 150  # counts are still reported


def test_report_withheld_when_one_class_is_rare():
    s = [i / 400 for i in range(400)]
    y = [1] * 5 + [0] * 395
    rep = evaluate_calibration(s, y, POLICY, seed=1, n_resamples=20)
    assert rep["metrics"] is None and any("smallest class" in r for r in rep["reasons"])


def test_report_above_n_has_metrics_intervals_and_no_calibration_claim():
    s, y = _sample(400, 4)
    rep = evaluate_calibration(s, y, POLICY, seed=1, n_resamples=30)
    assert rep["state"] == "estimate_reported" and rep["reasons"] == []
    m = rep["metrics"]
    for key in ("ece_width", "ece_mass"):
        assert m[key]["ci"]["lower"] <= m[key]["value"] <= m[key]["ci"]["upper"] or m[key]["ci"]["n_valid"]
        assert m[key]["ci"]["seed"] == 1
    assert {"brier", "log_loss", "reliability_curve_width", "reliability_curve_mass"} <= set(m)
    assert "calibrated" not in rep["state"].replace("uncalibrated", "")
    assert evaluate_calibration(s, y, POLICY, seed=1, n_resamples=30) == rep  # deterministic


def test_select_threshold_guard_forces_abstention_on_small_n():
    s, y = _sample(100, 8)
    for method in ("ltt", "crc"):
        d = select_threshold(method, s, y, 0.3, POLICY)  # type: ignore[arg-type]
        assert d.abstains_on_everything and "guard" in d.note
    s, y = _sample(800, 8)
    assert not select_threshold("crc", s, y, 0.3, POLICY).abstains_on_everything
    with pytest.raises(CalibrationInputError):
        select_threshold("nope", s, y, 0.3, POLICY)  # type: ignore[arg-type]
