from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from radius_shared.errors import NotFoundError

from radius_confidence.domain.entities import (
    AnalysisEvidence,
    ConfidenceReport,
    ImpactEvidence,
    TestEvidence,
    TestRunOutcome,
)
from radius_confidence.domain.enums import RiskLevel, VerificationStatus
from radius_confidence.domain.value_objects import CoveragePercent
from radius_confidence.dto.commands import (
    GenerateConfidenceReportCommand,
    GetCoverageForAnalysisCommand,
    GetCoverageForArtifactCommand,
    GetTestsForSymbolCommand,
    IngestCoverageCommand,
)
from radius_confidence.dto.responses import (
    ConfidenceReportResponse,
    CoverageArtifactResponse,
    CoverageFileResponse,
    CoverageReportResponse,
    CoverageSummaryResponse,
)
from radius_confidence.infrastructure.scoring import (
    analysis_evidence_from_report_evidence,
)
from radius_confidence.interfaces.scoring import ConfidenceScorer
from radius_confidence.interfaces.store import ConfidenceStore, CoverageStore

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

        report = self._build_report(
            analysis_id=command.analysis_id,
            impact=command.impact,
            tests=command.tests,
            analysis=command.analysis,
            source="Radius analysis",
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
        missing_selected_tests: tuple[str, ...] = (),
        *,
        selected_test_files: int | None = None,
        executed_selected_tests: tuple[str, ...] = (),
        failed_selected_tests: tuple[str, ...] = (),
        skipped_selected_tests: tuple[str, ...] = (),
        contradictory_tests: tuple[str, ...] = (),
    ) -> ConfidenceReportResponse:
        """Re-score an analysis after CI test results were ingested.

        The change-to-test mapping recorded by the original analysis is reused.
        If no mapping was recorded, the verdict cannot become ``verified``: a
        CI report alone does not prove the changed code was exercised.
        """

        existing = self._store.get_by_analysis_id(analysis_id)
        analysis = (
            analysis_evidence_from_report_evidence(existing.evidence)
            if existing is not None
            else None
        )
        if impact is None:
            impact = ImpactEvidence(
                affected_files=0,
                affected_symbols=0,
                affected_modules=0,
                affected_tests=test_result.total_tests,
                dependency_depth=0,
            )
        status = getattr(test_result, "status", None)
        status_value = getattr(status, "value", status)
        outcome = (
            TestRunOutcome.ERROR
            if status_value == "error"
            else TestRunOutcome.COMPLETED
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
            run_outcome=outcome,
            missing_selected_tests=missing_selected_tests,
            selected_test_files=selected_test_files,
            executed_selected_tests=executed_selected_tests,
            failed_selected_tests=failed_selected_tests,
            skipped_selected_tests=skipped_selected_tests,
            contradictory_tests=contradictory_tests,
            flaky=getattr(test_result, "flaky", 0),
            flaky_tests=tuple(getattr(test_result, "flaky_tests", ())),
        )
        report = self._build_report(
            analysis_id=analysis_id,
            impact=impact,
            tests=test_evidence,
            analysis=analysis,
            source="CI test results",
        )
        return ConfidenceReportResponse.from_entity(self._store.replace_report(report))

    def _build_report(
        self,
        *,
        analysis_id: UUID,
        impact: ImpactEvidence,
        tests: TestEvidence,
        analysis: AnalysisEvidence | None,
        source: str,
    ) -> ConfidenceReport:
        result = self._scorer.score(impact, tests, analysis)
        score, evidence = result[0], result[1]
        metrics = result.metrics
        status = metrics["verification_status"]
        gaps = tuple(metrics.get("verification_gaps", ()))
        return ConfidenceReport(
            id=None,
            analysis_id=analysis_id,
            confidence_score=score,
            risk_level=self._risk_level(score.value),
            summary=self._summary(status, score.value, gaps, source),
            evidence=evidence,
            recommendations=self._recommendations(status, score.value, gaps),
            change_risk=metrics["change_risk"],
            verification_confidence=metrics["verification_confidence"],
            analysis_completeness=metrics["analysis_completeness"],
            verification_status=status,
        )

    @staticmethod
    def _summary(
        status: str,
        score: float,
        gaps: tuple[str, ...],
        source: str,
    ) -> str:
        verdict = {
            VerificationStatus.VERIFIED.value: (
                "Verified: every executable change is covered by selected tests "
                "that ran and passed."
            ),
            VerificationStatus.FAILED.value: "Failed: at least one selected test failed.",
            VerificationStatus.INSUFFICIENT_EVIDENCE.value: (
                "Not verified: Radius does not have enough evidence to call this "
                "change safe."
            ),
        }.get(status, f"Verdict: {status}.")
        detail = f" Gaps: {'; '.join(gaps)}." if gaps else ""
        return (
            f"{verdict}{detail} Heuristic score {score:.1f}/100 from {source} "
            "(not a calibrated probability)."
        )

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
    def _recommendations(
        status: str,
        score: float,
        gaps: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        if status == VerificationStatus.FAILED.value:
            return ("Block merge until the failing selected tests are fixed.",)
        if status == VerificationStatus.INSUFFICIENT_EVIDENCE.value:
            return (
                "Do not treat this pull request as verified.",
                *(f"Resolve: {gap}." for gap in gaps),
                "Run the full test suite or add tests that exercise the unmapped changes.",
            )
        if score >= 85:
            return ("Proceed with standard review.",)
        return ("Selected tests passed, but the blast radius is large; review impacted files.",)


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
