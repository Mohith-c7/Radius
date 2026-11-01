"""Confidence scoring interfaces."""

from typing import Any, Protocol

from radius_confidence.domain.entities import (
    AnalysisEvidence,
    ConfidenceEvidence,
    ImpactEvidence,
    TestEvidence,
)
from radius_confidence.domain.value_objects import ConfidenceScore


class ScoringResult(tuple):
    """Result of confidence scoring that unpacks as (score, evidence) for backward compatibility."""

    def __new__(
        cls,
        score: ConfidenceScore,
        evidence: tuple[ConfidenceEvidence, ...],
        metrics: dict[str, Any],
    ) -> "ScoringResult":
        obj = super().__new__(cls, (score, evidence))
        obj.metrics = metrics
        return obj

class ConfidenceScorer(Protocol):
    """Contract for deterministic confidence scoring."""

    def score(
        self,
        impact: ImpactEvidence,
        tests: TestEvidence,
        analysis: AnalysisEvidence | None = None,
    ) -> ScoringResult:
        """Return score, evidence, and decoupled confidence metrics."""
