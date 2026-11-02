"""Confidence domain enum values."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    """Confidence risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceCategory(StrEnum):
    """Confidence evidence categories."""

    BLAST_RADIUS = "blast_radius"
    TESTS = "tests"
    COVERAGE = "coverage"
    ANALYSIS = "analysis"


class VerificationStatus(StrEnum):
    """Evidence-gated merge verdict.

    ``VERIFIED`` is only produced when every executable change is mapped to
    selected tests that actually ran to completion and passed.
    """

    VERIFIED = "verified"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ScoreKind(StrEnum):
    """How the 0-100 confidence score should be interpreted.

    The v1 score is a heuristic built from fixed penalties; it is not a
    calibrated probability. Once calibration (CA-*) ships and the feature flag
    (VD-07) exists, switch ``CURRENT_SCORE_KIND`` -- call sites read only that.
    """

    HEURISTIC_UNCALIBRATED = "heuristic_uncalibrated"
    CALIBRATED = "calibrated"


#: Single source of truth for the kind of score Radius currently emits.
CURRENT_SCORE_KIND = ScoreKind.HEURISTIC_UNCALIBRATED


class EvidenceImpact(StrEnum):
    """Evidence score impact."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
