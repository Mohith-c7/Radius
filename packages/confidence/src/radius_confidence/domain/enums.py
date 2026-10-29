"""Confidence domain enum values."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Backport of Python 3.11 StrEnum for Python 3.9."""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


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
