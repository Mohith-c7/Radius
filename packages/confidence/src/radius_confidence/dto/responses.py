"""Confidence response DTOs."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_confidence.domain.entities import ConfidenceEvidence, ConfidenceReport


@dataclass(frozen=True, slots=True)
class ConfidenceEvidenceResponse:
    """Confidence evidence response DTO."""

    category: str
    label: str
    message: str
    impact: str
    value: float | None

    @classmethod
    def from_entity(
        cls,
        evidence: ConfidenceEvidence,
    ) -> "ConfidenceEvidenceResponse":
        """Create a response DTO from confidence evidence."""

        return cls(
            category=evidence.category.value,
            label=evidence.label,
            message=evidence.message,
            impact=evidence.impact.value,
            value=evidence.value,
        )


@dataclass(frozen=True, slots=True)
class ConfidenceReportResponse:
    """Confidence report response DTO."""

    id: UUID | None
    analysis_id: UUID
    confidence_score: float
    risk_level: str
    summary: str
    evidence: tuple[ConfidenceEvidenceResponse, ...]
    recommendations: tuple[str, ...]
    generated_at: datetime

    @classmethod
    def from_entity(cls, report: ConfidenceReport) -> "ConfidenceReportResponse":
        """Create a response DTO from a confidence report."""

        return cls(
            id=report.id,
            analysis_id=report.analysis_id,
            confidence_score=report.confidence_score.value,
            risk_level=report.risk_level.value,
            summary=report.summary,
            evidence=tuple(
                ConfidenceEvidenceResponse.from_entity(item)
                for item in report.evidence
            ),
            recommendations=report.recommendations,
            generated_at=report.generated_at,
        )
