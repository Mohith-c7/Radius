"""Confidence response DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_confidence.domain.entities import ConfidenceEvidence, ConfidenceReport
from radius_confidence.domain.enums import CURRENT_SCORE_KIND

__all__ = [
    "CoverageArtifactResponse",
    "CoverageFileResponse",
    "CoverageReportResponse",
    "CoverageSummaryResponse",
    "ConfidenceEvidenceResponse",
    "ConfidenceReportResponse",
]



@dataclass(frozen=True)
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
    ) -> ConfidenceEvidenceResponse:
        """Create a response DTO from confidence evidence."""

        return cls(
            category=evidence.category.value,
            label=evidence.label,
            message=evidence.message,
            impact=evidence.impact.value,
            value=evidence.value,
        )


@dataclass(frozen=True)
class CoverageArtifactResponse:
    """One normalized coverage line."""

    test_id: UUID
    test_path: str
    file_path: str
    symbol: str | None
    executed: bool
    count: int
    covered: bool


@dataclass(frozen=True)
class CoverageFileResponse:
    """Aggregated coverage for a source file."""

    file_path: str
    source_language: str
    covered_lines: int
    total_lines: int
    covered_percent: float | None


@dataclass(frozen=True)
class CoverageSummaryResponse:
    """Aggregated coverage for an analysis."""

    covered_lines: int
    total_lines: int
    coverage_percent: float | None
    artifact_count: int
    available: bool

    def __getitem__(self, key: str):
        """Keep compatibility with existing dictionary-shaped callers."""
        return getattr(self, key)


@dataclass(frozen=True)
class CoverageReportResponse:
    """Full coverage payload for one analysis."""

    analysis_id: UUID
    framework: str
    coverage_percent: float | None
    covered_lines: int
    total_lines: int
    files: tuple[CoverageFileResponse, ...]
    artifacts: tuple[CoverageArtifactResponse, ...]
    generated_at: datetime


@dataclass(frozen=True)
class ConfidenceReportResponse:
    """Final confidence report response DTO."""

    id: UUID | None
    analysis_id: UUID
    confidence_score: float
    risk_level: str
    summary: str
    evidence: tuple
    recommendations: tuple[str, ...]
    change_risk: str
    verification_confidence: float
    analysis_completeness: float
    verification_status: str
    generated_at: datetime
    score_kind: str = CURRENT_SCORE_KIND.value

    @classmethod
    def from_entity(cls, report: ConfidenceReport) -> ConfidenceReportResponse:
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
            change_risk=report.change_risk,
            verification_confidence=report.verification_confidence,
            analysis_completeness=report.analysis_completeness,
            verification_status=report.verification_status,
            generated_at=report.generated_at,
            score_kind=report.score_kind.value,
        )
