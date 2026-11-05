"""Calibration toolkit for the future trust probability (CA-03 to CA-05 groundwork).

Pure, stdlib-only. **Nothing here is wired into the verdict.** Verdict v2 is
uncalibrated (``calibrated: false``); this package is the measurement and
guard machinery that must exist before a calibrated number can honestly be
shown, plus the :class:`Calibrator` hook point. Nothing in it is a research
result: it has been tested on hand-computed cases and seeded simulations only.

See ``docs/research/evaluation/CALIBRATION_TOOLKIT.md``.
"""

from .calibrators import IsotonicCalibrator, PlattCalibrator, UncalibratedPrior
from .guards import (
    CalibrationPolicy,
    ReportState,
    evaluate_calibration,
    fit_calibrator,
    select_threshold,
)
from .intervals import (
    BootstrapInterval,
    bootstrap_ci,
    clopper_pearson,
    clopper_pearson_lower,
    clopper_pearson_upper,
)
from .metrics import (
    BrierDecomposition,
    ReliabilityBin,
    brier_decomposition,
    brier_score,
    ece,
    ece_noise_floor,
    expected_calibration_error,
    log_loss,
    max_calibration_error,
    reliability_bins,
    reliability_curve,
)
from .protocol import CalibratedScore, CalibrationState, Calibrator
from .risk_control import (
    RiskCoveragePoint,
    ThresholdDecision,
    crc_threshold,
    evaluate_threshold,
    find_nonincreasing_violation,
    ltt_threshold,
    prereg_shifted_loss,
    risk_coverage_curve,
)

__all__ = [
    "BootstrapInterval",
    "BrierDecomposition",
    "CalibratedScore",
    "CalibrationPolicy",
    "CalibrationState",
    "Calibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "ReliabilityBin",
    "ReportState",
    "RiskCoveragePoint",
    "ThresholdDecision",
    "UncalibratedPrior",
    "bootstrap_ci",
    "brier_decomposition",
    "brier_score",
    "clopper_pearson",
    "clopper_pearson_lower",
    "clopper_pearson_upper",
    "crc_threshold",
    "ece",
    "ece_noise_floor",
    "evaluate_calibration",
    "evaluate_threshold",
    "expected_calibration_error",
    "find_nonincreasing_violation",
    "fit_calibrator",
    "log_loss",
    "ltt_threshold",
    "max_calibration_error",
    "prereg_shifted_loss",
    "reliability_bins",
    "reliability_curve",
    "risk_coverage_curve",
    "select_threshold",
]
