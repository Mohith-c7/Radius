"""Confidence scoring interfaces."""

from typing import Protocol

from radius_confidence.domain.entities import (
    ConfidenceEvidence,
    ImpactEvidence,
    TestEvidence,
)
from radius_confidence.domain.value_objects import ConfidenceScore


class ConfidenceScorer(Protocol):
    """Contract for deterministic confidence scoring."""

    def score(
        self,
        impact: ImpactEvidence,
        tests: TestEvidence,
    ) -> tuple[ConfidenceScore, tuple[ConfidenceEvidence, ...]]:
        """Return score and evidence."""
