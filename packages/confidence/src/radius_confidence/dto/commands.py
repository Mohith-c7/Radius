"""Confidence application command DTOs."""

from dataclasses import dataclass
from uuid import UUID

from radius_confidence.domain.entities import (
    AnalysisEvidence,
    ImpactEvidence,
    TestEvidence,
)


@dataclass(frozen=True, slots=True)
class GenerateConfidenceReportCommand:
    """Command to generate a deterministic confidence report."""

    analysis_id: UUID
    impact: ImpactEvidence
    tests: TestEvidence
    analysis: AnalysisEvidence | None = None
