"""Confidence application service."""

from uuid import UUID

from radius_shared.errors import NotFoundError

from radius_confidence.domain.entities import ConfidenceReport
from radius_confidence.domain.enums import RiskLevel
from radius_confidence.dto.commands import GenerateConfidenceReportCommand
from radius_confidence.dto.responses import ConfidenceReportResponse
from radius_confidence.interfaces.scoring import ConfidenceScorer
from radius_confidence.interfaces.store import ConfidenceStore


class ConfidenceApplicationService:
    """Coordinates deterministic confidence report generation."""

    def __init__(self, scorer: ConfidenceScorer, store: ConfidenceStore) -> None:
        self._scorer = scorer
        self._store = store

    def generate_report(
        self,
        command: GenerateConfidenceReportCommand,
    ) -> ConfidenceReportResponse:
        """Generate and persist a confidence report."""

        score, evidence = self._scorer.score(command.impact, command.tests)
        report = ConfidenceReport(
            id=None,
            analysis_id=command.analysis_id,
            confidence_score=score,
            risk_level=self._risk_level(score.value),
            summary=f"Confidence score is {score.value:.1f}.",
            evidence=evidence,
            recommendations=self._recommendations(score.value),
        )
        return ConfidenceReportResponse.from_entity(self._store.save_report(report))

    def get_report(self, analysis_id: UUID) -> ConfidenceReportResponse:
        """Return a saved confidence report."""

        report = self._store.get_by_analysis_id(analysis_id)
        if report is None:
            msg = f"Confidence report for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return ConfidenceReportResponse.from_entity(report)

    @staticmethod
    def _risk_level(score: float) -> RiskLevel:
        if score >= 85:
            return RiskLevel.LOW
        if score >= 70:
            return RiskLevel.MEDIUM
        if score >= 50:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    @staticmethod
    def _recommendations(score: float) -> tuple[str, ...]:
        if score >= 85:
            return ("Proceed with standard review.",)
        if score >= 70:
            return ("Review impacted files and confirm selected tests.",)
        if score >= 50:
            return ("Add focused tests before merging.",)
        return ("Block merge until failures and coverage gaps are resolved.",)
