"""Confidence application services.

Confidence reports are generated deterministically, persisted to a
ConfidenceStore, and returned as response DTOs. Coverage reports are read
back from a CoverageStore and normalized into the confidence response DTOs.
"""

from typing import Iterable

from radius_confidence.domain.entities import CoverageEvidence, ConfidenceEvidence
from radius_confidence.domain.enums import EvidenceCategory, EvidenceImpact, RiskLevel
from radius_confidence.domain.value_objects import CoveragePercent
from radius_confidence.domain.entities import ConfidenceReport
from radius_confidence.interfaces.scoring import ConfidenceScorer
from radius_confidence.interfaces.store import (
    ConfidenceStore,
    CoverageStore,
)
from radius_shared.errors import NotFoundError

from radius_confidence.dto.commands import (
    GenerateConfidenceReportCommand,
    GetCoverageForAnalysisCommand,
    GetCoverageForArtifactCommand,
    GetTestsForSymbolCommand,
    IngestCoverageCommand,
)
from radius_confidence.dto.responses import (
    ConfidenceEvidenceResponse,
    ConfidenceReportResponse,
    CoverageArtifactResponse,
    CoverageFileResponse,
    CoverageReportResponse,
    CoverageSummaryResponse,
)


class ConfidenceApplicationService:
    """Application service for generating and retrieving confidence reports."""

    def __init__(self, scorer: ConfidenceScorer, store: ConfidenceStore) -> None:
        self._scorer = scorer
        self._store = store

    def generate_report(self, command: GenerateConfidenceReportCommand) -> ConfidenceReportResponse:
        """Generate a deterministic confidence report and persist it."""

        score, evidence = self._scorer.score(command.impact, command.tests)

        risk_level = self._risk_level_for(score.value)
        summary = self._summary_for(score.value, risk_level)

        report = ConfidenceReport(
            id=None,
            analysis_id=command.analysis_id,
            confidence_score=score,
            risk_level=risk_level,
            summary=summary,
            evidence=tuple(self._evidences(score, evidence)),
            recommendations=self._recommendations(score.value, risk_level),
        )

        saved = self._store.save_report(report)
        return ConfidenceReportResponse.from_entity(saved)

    def get_report(self, analysis_id: str) -> ConfidenceReportResponse:
        """Return the persisted confidence report for an analysis."""

        report = self._store.get_by_analysis_id(analysis_id)
        if report is None:
            msg = f"Confidence report for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return ConfidenceReportResponse.from_entity(report)

    @staticmethod
    def _risk_level_for(score: float) -> RiskLevel:
        if score >= 80:
            return RiskLevel.LOW
        if score >= 60:
            return RiskLevel.MEDIUM
        if score >= 40:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    @staticmethod
    def _summary_for(score: float, risk_level: RiskLevel) -> str:
        return (
            f"Confidence {score:.0f}/100 is {risk_level}. "
            f"The change has been verified against the current evidence."
        )

    @staticmethod
    def _recommendations(score: float, risk_level: RiskLevel) -> tuple[str, ...]:
        if risk_level == RiskLevel.LOW:
            return ("Proceed with standard review.",)
        if risk_level == RiskLevel.MEDIUM:
            return ("Add regression tests for the changed blast radius.",)
        if risk_level == RiskLevel.HIGH:
            return (
                "Review the affected blast radius before merging.",
                "Add targeted tests for the changed paths.",
            )
        return (
            "Do not merge until the blast radius and coverage are reviewed.",
            "Add regression tests for every affected file and module.",
        )

    @staticmethod
    def _evidences(score: float, evidence: tuple[ConfidenceEvidence, ...]) -> list[ConfidenceEvidence]:
        if score == 100:
            return [
                ConfidenceEvidence(
                    category=EvidenceCategory.BLAST_RADIUS,
                    label="baseline",
                    message="Confidence starts at 100 and is only reduced by evidence.",
                    impact=EvidenceImpact.POSITIVE,
                    value=100,
                )
            ]
        return list(evidence)

    def _save_report(self, report: ConfidenceReport) -> ConfidenceReport:
        try:
            return self._store.save_report(report)
        except ValueError as exc:
            msg = f"Could not persist confidence report: {exc}"
            raise ValueError(msg) from exc


class CoverageApplicationService:
    """Application service for runtime coverage, independent of confidence scoring."""

    def __init__(
        self,
        scorer: ConfidenceScorer,
        confidence_store: ConfidenceStore,
        coverage_store: CoverageStore,
    ) -> None:
        self._scorer = scorer
        self._confidence_store = confidence_store
        self._coverage_store = coverage_store

    def ingest_coverage(self, command: IngestCoverageCommand) -> None:
        """Persist the artifacts produced by one test run."""

        self._coverage_store.ingest_coverage(
            command.analysis_id,
            command.framework,
            command.coverage_percent,
            command.files or (),
            command.symbols or (),
        )

    def get_coverage_for_artifact(self, command: GetCoverageForArtifactCommand) -> dict | None:
        return self._coverage_store.get_coverage_for_artifact(command.analysis_id, command.path)

    def get_tests_for_symbol(self, command: GetTestsForSymbolCommand) -> dict | None:
        return self._coverage_store.get_tests_for_symbol(command.analysis_id, command.file_path, command.symbol)

    def get_coverage_summary(self, command: GetCoverageForAnalysisCommand) -> CoverageSummaryResponse | None:
        summary = self._coverage_store.get_summary(command.analysis_id)
        if summary is None:
            return None
        return CoverageSummaryResponse(
            covered_lines=summary["covered_lines"],
            total_lines=summary["total_lines"],
            coverage_percent=summary["coverage_percent"],
            artifact_count=summary["artifact_count"],
            available=summary["available"],
        )

    def get_coverage_report(self, command: GetCoverageForAnalysisCommand) -> CoverageReportResponse | None:
        payload = self._coverage_store.get_report(command.analysis_id)
        if payload is None:
            return None
        return self._to_coverage_report(payload)

    def _to_coverage_report(self, payload: dict) -> CoverageReportResponse:
        report = payload["report"]
        files = []
        for item in payload.get("files", []):
            files.append(
                CoverageFileResponse(
                    file_path=item["file_path"],
                    source_language=item.get("source_language", "unknown"),
                    covered_lines=item.get("covered_lines", 0),
                    total_lines=item.get("total_lines", 0),
                    covered_percent=item.get("covered_percent"),
                )
            )
        artifacts = []
        for item in payload.get("artifacts", []):
            artifacts.append(
                CoverageArtifactResponse(
                    test_id=item["test_id"],
                    test_path=item.get("test_path", ""),
                    file_path=item.get("file_path", ""),
                    symbol=item.get("symbol"),
                    executed=item.get("executed", False),
                    count=item.get("count", 0),
                    covered=item.get("covered", False),
                )
            )
        return CoverageReportResponse(
            analysis_id=report["analysis_id"],
            framework=report.get("framework", "unknown"),
            coverage_percent=report.get("coverage_percent"),
            covered_lines=report.get("covered_lines", 0),
            total_lines=report.get("total_lines", 0),
            files=tuple(files),
            artifacts=tuple(artifacts),
            generated_at=report.get("created_at") or report.get("updated_at"),
        )
