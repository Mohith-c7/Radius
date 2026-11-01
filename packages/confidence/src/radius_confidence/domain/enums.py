"""Confidence domain enum values."""

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


class EvidenceImpact(StrEnum):
    """Evidence score impact."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
