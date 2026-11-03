"""Minimum-sample guards: refuse to report a calibration number below a declared N.

The guard is the point of this module. A calibration metric on 40 items is
mostly noise (the expected ECE of a perfectly calibrated model at N = 250 is
already ~0.06 in the preregistration draft's own simulation), and a displayed
"87% confident" invites trust the data cannot support. Below the declared
minimum the functions here return the ``UNCALIBRATED_PRIOR`` state and **no
number**; at or above it they return estimates with intervals and the state
``ESTIMATE_REPORTED``, which is not a claim that the model is calibrated.

``CalibrationPolicy`` has no defaults on purpose: the minimum N values are
analysis choices that belong in the pre-registration. The draft
(``PREREGISTRATION.md`` 7.1, 7.2, 7.5) mentions N_test >= 2,000 for the ECE
hypothesis and isotonic only from 1,000 calibration items; those are draft
"initial guesses", not frozen, and nothing here hard-codes them.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ._validate import CalibrationInputError, check_scores_labels
from .calibrators import IsotonicCalibrator, PlattCalibrator, UncalibratedPrior
from .intervals import BootstrapInterval, bootstrap_ci
from .metrics import (
    BinStrategy,
    brier_decomposition,
    brier_score,
    ece,
    expected_calibration_error,
    log_loss,
    max_calibration_error,
    reliability_bins,
    reliability_curve,
)
from .protocol import Calibrator
from .risk_control import (
    DEFAULT_GRID,
    ThresholdDecision,
    crc_threshold,
    ltt_threshold,
    risk_coverage_curve,
)


class ReportState(StrEnum):
    UNCALIBRATED_PRIOR = "uncalibrated_prior"
    ESTIMATE_REPORTED = "estimate_reported"


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    """Declared minimum sample sizes. All fields are required."""

    min_n_report: int
    min_per_class: int
    min_n_fit: int
    isotonic_min_n: int
    min_n_threshold: int
    min_bin_count: int = 10

    def __post_init__(self) -> None:
        for name in (
            "min_n_report", "min_per_class", "min_n_fit", "isotonic_min_n",
            "min_n_threshold", "min_bin_count",
        ):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise CalibrationInputError(f"policy.{name} must be an int >= 1")

    def to_dict(self) -> dict:
        return {
            "min_n_report": self.min_n_report,
            "min_per_class": self.min_per_class,
            "min_n_fit": self.min_n_fit,
            "isotonic_min_n": self.isotonic_min_n,
            "min_n_threshold": self.min_n_threshold,
            "min_bin_count": self.min_bin_count,
        }


def insufficiency_reasons(n: int, n_pos: int, n_neg: int, min_n: int, min_per_class: int) -> list[str]:
    reasons = []
    if n < min_n:
        reasons.append(f"N={n} is below the declared minimum {min_n}")
    if min(n_pos, n_neg) < min_per_class:
        reasons.append(
            f"smallest class has {min(n_pos, n_neg)} items, below the declared minimum {min_per_class}"
        )
    return reasons


def _ci(stat, ps, ys, *, seed, n_resamples, confidence, clusters) -> BootstrapInterval:
    return bootstrap_ci(
        stat, ps, ys, seed=seed, n_resamples=n_resamples, confidence=confidence, clusters=clusters
    )


def evaluate_calibration(
    scores: Sequence[float],
    labels: Sequence[int],
    policy: CalibrationPolicy,
    *,
    seed: int,
    n_bins: int = 10,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    clusters: Sequence[Hashable] | None = None,
) -> dict:
    """Calibration report for one set of predictions, guarded by ``policy``.

    The result is a JSON-serialisable dict. ``state`` is ``uncalibrated_prior``
    when N or a class count is below the declared minimum; then ``metrics`` is
    ``None`` and only counts and ``reasons`` are given. Otherwise ``metrics``
    holds ECE (equal-width and equal-mass) with bootstrap intervals, MCE, Brier
    with decomposition and interval, log loss with interval, reliability curve
    data, and ``warnings`` for sparse bins. The report never says "calibrated".
    """

    ps, ys = check_scores_labels(scores, labels, allow_empty=True)
    n = len(ps)
    n_pos = sum(ys)
    n_neg = n - n_pos
    reasons = insufficiency_reasons(n, n_pos, n_neg, policy.min_n_report, policy.min_per_class)
    out: dict = {
        "n": n,
        "n_positive": n_pos,
        "n_negative": n_neg,
        "base_rate": (n_pos / n) if n else None,
        "policy": policy.to_dict(),
        "state": ReportState.UNCALIBRATED_PRIOR.value,
        "reasons": reasons,
        "metrics": None,
        "warnings": [],
    }
    if reasons:
        out["reasons"] = reasons + [
            "no calibration number is reported; treat the score as an uncalibrated prior"
        ]
        return out

    kw = {"seed": seed, "n_resamples": n_resamples, "confidence": confidence, "clusters": clusters}
    metrics: dict = {"n_bins": n_bins}
    warnings: list[str] = []
    for strat in ("width", "mass"):
        strategy: BinStrategy = strat  # type: ignore[assignment]
        bins = reliability_bins(ps, ys, n_bins, strategy)
        ci = _ci(lambda s, y, st=strategy: ece(s, y, n_bins, st), ps, ys, **kw)
        metrics[f"ece_{strat}"] = {
            "value": expected_calibration_error(bins),
            "ci": ci.to_dict(),
            "mce": max_calibration_error(bins),
            "note": (
                "ECE is biased upward at small N; compare with the noise floor of a "
                "perfectly calibrated model at the same N before reading it"
            ),
        }
        sparse = [b.index for b in bins if 0 < b.count < policy.min_bin_count]
        if sparse:
            warnings.append(
                f"{strat}-bin ECE: bins {sparse} hold fewer than {policy.min_bin_count} items"
            )
    metrics["brier"] = {
        "value": brier_score(ps, ys),
        "ci": _ci(brier_score, ps, ys, **kw).to_dict(),
        "decomposition_width": brier_decomposition(ps, ys, n_bins, "width").to_dict(),
        "decomposition_mass": brier_decomposition(ps, ys, n_bins, "mass").to_dict(),
    }
    metrics["log_loss"] = {
        "value": log_loss(ps, ys),
        "ci": _ci(log_loss, ps, ys, **kw).to_dict(),
    }
    metrics["reliability_curve_width"] = reliability_curve(ps, ys, n_bins, "width")
    metrics["reliability_curve_mass"] = reliability_curve(ps, ys, n_bins, "mass")
    out.update(
        state=ReportState.ESTIMATE_REPORTED.value,
        reasons=[],
        metrics=metrics,
        warnings=warnings,
    )
    return out


def fit_calibrator(
    method: Literal["auto", "isotonic", "platt"],
    scores: Sequence[float],
    labels: Sequence[int],
    policy: CalibrationPolicy,
) -> Calibrator:
    """Fit a calibrator, or return an :class:`UncalibratedPrior` that says why not.

    ``auto`` follows the preregistration draft's rule: isotonic from
    ``policy.isotonic_min_n`` items, otherwise Platt. An explicit ``isotonic``
    below ``isotonic_min_n`` is refused too. Fit on a calibration split only;
    measure on a different one.
    """

    if method not in ("auto", "isotonic", "platt"):
        raise CalibrationInputError(f"unknown method {method!r}")
    ps, ys = check_scores_labels(scores, labels, allow_empty=True)
    n, n_pos = len(ps), sum(ys)
    reasons = insufficiency_reasons(n, n_pos, n - n_pos, policy.min_n_fit, policy.min_per_class)
    chosen = method
    if method == "auto":
        chosen = "isotonic" if n >= policy.isotonic_min_n else "platt"
    if chosen == "isotonic" and n < policy.isotonic_min_n:
        reasons.append(f"isotonic needs N >= {policy.isotonic_min_n}, got {n}")
    if reasons:
        return UncalibratedPrior(reason="; ".join(reasons), n_fit=0)
    if chosen == "isotonic":
        return IsotonicCalibrator.fit(ps, ys)
    return PlattCalibrator.fit(ps, ys)


def select_threshold(
    method: Literal["ltt", "crc"],
    confidence: Sequence[float],
    correct: Sequence[int],
    alpha: float,
    policy: CalibrationPolicy,
    *,
    delta: float = 0.10,
    grid: Sequence[float] = DEFAULT_GRID,
) -> ThresholdDecision:
    """Abstention threshold, guarded: too few calibration items means abstain on everything."""

    if method not in ("ltt", "crc"):
        raise CalibrationInputError(f"unknown method {method!r}")
    cs, ok = check_scores_labels(confidence, correct, allow_empty=True)
    n = len(cs)
    reasons = insufficiency_reasons(
        n, sum(ok), n - sum(ok), policy.min_n_threshold, 1
    )
    if reasons:
        proto = ltt_threshold([], [], alpha, delta, grid) if method == "ltt" else crc_threshold([], [], alpha)
        return ThresholdDecision(
            proto.method, proto.risk_kind, alpha, proto.delta, None, n, 0, 0, None,
            proto.guarantee, proto.assumptions,
            note="guard: " + "; ".join(reasons) + "; abstain on everything",
        )
    if method == "ltt":
        return ltt_threshold(cs, ok, alpha, delta, grid)
    return crc_threshold(cs, ok, alpha)


__all__ = [
    "CalibrationPolicy",
    "ReportState",
    "evaluate_calibration",
    "fit_calibrator",
    "risk_coverage_curve",
    "select_threshold",
]
