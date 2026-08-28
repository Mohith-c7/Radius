"""Confidence domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from radius_confidence.domain.enums import (
    EvidenceCategory,
    EvidenceImpact,
    RiskLevel,
)
from radius_confidence.domain.value_objects import ConfidenceScore, CoveragePercent


@dataclass(frozen=True, slots=True)
class ImpactEvidence:
    """Blast-radius evidence for confidence scoring."""

    affected_files: int
    affected_symbols: int
    affected_modules: int
    affected_tests: int
    dependency_depth: int


@dataclass(frozen=True, slots=True)
class TestEvidence:
    """Test evidence for confidence scoring."""

    total_tests: int
    passed: int
    failed: int
    skipped: int
    coverage_percent: CoveragePercent | None = None


@dataclass(frozen=True, slots=True)
class ConfidenceEvidence:
    """One explainable confidence scoring fact."""

    category: EvidenceCategory
    label: str
    message: str
    impact: EvidenceImpact = EvidenceImpact.NEUTRAL
    value: float | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            msg = "Evidence label cannot be empty."
            raise ValueError(msg)
        if not self.message.strip():
            msg = "Evidence message cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ConfidenceReport:
    """Final deterministic confidence report."""

    id: UUID | None
    analysis_id: UUID
    confidence_score: ConfidenceScore
    risk_level: RiskLevel
    summary: str
    evidence: tuple[ConfidenceEvidence, ...]
    recommendations: tuple[str, ...]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.summary.strip():
            msg = "Confidence report summary cannot be empty."
            raise ValueError(msg)
        if not self.evidence:
            msg = "Confidence report requires evidence."
            raise ValueError(msg)
