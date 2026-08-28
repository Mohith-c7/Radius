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


class EvidenceImpact(StrEnum):
    """Evidence score impact."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
