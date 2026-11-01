"""Confidence domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from radius_confidence.domain.enums import (
    EvidenceCategory,
    EvidenceImpact,
    RiskLevel,
)
from radius_confidence.domain.value_objects import ConfidenceScore, CoveragePercent


@dataclass(frozen=True)
class ImpactEvidence:
    """Blast-radius evidence for confidence scoring."""

    affected_files: int
    affected_symbols: int
    affected_modules: int
    affected_tests: int
    dependency_depth: int


class TestRunOutcome:
    """How (and whether) the selected tests were executed.

    Only ``COMPLETED`` runs can contribute positive verification evidence.
    """

    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class TestEvidence:
    """Test evidence for confidence scoring."""

    total_tests: int
    passed: int
    failed: int
    skipped: int
    coverage_percent: CoveragePercent | None = None
    run_outcome: str = TestRunOutcome.COMPLETED
    run_detail: str | None = None
    missing_selected_tests: tuple[str, ...] = ()
    """Selected test files that the results do not show as executed."""
    selected_test_files: int | None = None
    """Number of selected test files, when results were attributed to a selection.

    ``None`` means attribution was not performed (for example a worker-run
    suite). ``0`` with executable changes means nothing could be attributed.
    """
    executed_selected_tests: tuple[str, ...] = ()
    """Selected test files with at least one executed (passed or failed) case."""
    failed_selected_tests: tuple[str, ...] = ()
    """Selected test files with at least one failed case."""
    skipped_selected_tests: tuple[str, ...] = ()
    """Selected test files whose reported cases were all skipped."""
    contradictory_tests: tuple[str, ...] = ()
    """Test cases reported as passed in one upload and failed in another."""


@dataclass(frozen=True, slots=True)
class AnalysisEvidence:
    """How completely the changed files were mapped to executed tests.

    Every changed file must land in exactly one bucket. A change can only be
    reported as verified when ``unmapped_files``, ``unanalyzed_files`` and
    ``parse_failures`` are all empty.
    """

    changed_files: int
    covered_files: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    unanalyzed_files: tuple[str, ...] = ()
    non_executable_files: tuple[str, ...] = ()
    parse_failures: tuple[str, ...] = ()
    full_suite_fallback_reasons: tuple[str, ...] = ()

    @property
    def executable_changes(self) -> int:
        """Return the number of changed files that can affect runtime behavior."""

        return self.changed_files - len(self.non_executable_files)

    @property
    def gaps(self) -> tuple[str, ...]:
        """Return human-readable reasons the mapping is incomplete."""

        reasons: list[str] = []
        if self.unmapped_files:
            reasons.append(
                f"{len(self.unmapped_files)} changed file(s) are not reached by any "
                "discovered test"
            )
        if self.unanalyzed_files:
            reasons.append(
                f"{len(self.unanalyzed_files)} changed file(s) are in a format Radius "
                "cannot analyze"
            )
        if self.parse_failures:
            reasons.append(
                f"{len(self.parse_failures)} source file(s) failed to parse, so the "
                "dependency graph is incomplete"
            )
        return tuple(reasons)


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class CoverageEvidence:
    """One explainable runtime coverage fact."""

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


@dataclass(frozen=True)
class ConfidenceReport:
    """Final deterministic confidence report."""

    id: UUID | None
    analysis_id: UUID
    confidence_score: ConfidenceScore
    risk_level: RiskLevel
    summary: str
    evidence: tuple[ConfidenceEvidence, ...]
    recommendations: tuple[str, ...]
    change_risk: str = "low"
    verification_confidence: float = 100.0
    analysis_completeness: float = 100.0
    verification_status: str = "unverified"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.summary.strip():
            msg = "Confidence report summary cannot be empty."
            raise ValueError(msg)
        if not self.evidence:
            msg = "Confidence report requires evidence."
            raise ValueError(msg)
