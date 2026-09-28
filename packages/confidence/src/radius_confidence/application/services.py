from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from radius_shared.errors import NotFoundError

from radius_confidence.domain.entities import (
    ConfidenceReport,
    ImpactEvidence,
    TestEvidence,
)
from radius_confidence.domain.enums import RiskLevel
from radius_confidence.domain.value_objects import CoveragePercent
from radius_confidence.dto.commands import GenerateConfidenceReportCommand
from radius_confidence.dto.responses import ConfidenceReportResponse
from radius_confidence.interfaces.scoring import ConfidenceScorer
from radius_confidence.interfaces.store import ConfidenceStore

if TYPE_CHECKING:
    from radius_testing.domain.entities import TestRunResult
    from radius_testing.dto.responses import TestRunResultResponse



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

    def recalculate_from_test_results(
        self,
        analysis_id: UUID,
        test_result: TestRunResultResponse | TestRunResult,
        impact: ImpactEvidence | None = None,
    ) -> ConfidenceReportResponse:
        """Recalculate confidence score and report from CI test run results."""
        existing = self._store.get_by_analysis_id(analysis_id)
        if impact is None:
            # Try to get impact from existing report if present, or use safe default
            impact = ImpactEvidence(
                affected_files=1,
                affected_symbols=1,
                affected_modules=1,
                affected_tests=test_result.total_tests,
                dependency_depth=1,
            )
        test_evidence = TestEvidence(
            total_tests=test_result.total_tests,
            passed=test_result.passed,
            failed=test_result.failed,
            skipped=test_result.skipped,
            coverage_percent=(
                CoveragePercent(test_result.coverage_percent)
                if getattr(test_result, "coverage_percent", None) is not None
                else None
            ),
        )
        score, evidence = self._scorer.score(impact, test_evidence)
        report = ConfidenceReport(
            id=None,
            analysis_id=analysis_id,
            confidence_score=score,
            risk_level=self._risk_level(score.value),
            summary=f"Confidence score updated from CI test run: {score.value:.1f}.",
            evidence=evidence,
            recommendations=self._recommendations(score.value),
        )
        if existing is not None and hasattr(self._store, "_reports"):
            self._store._reports.pop(analysis_id, None)
        return ConfidenceReportResponse.from_entity(self._store.save_report(report))


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
