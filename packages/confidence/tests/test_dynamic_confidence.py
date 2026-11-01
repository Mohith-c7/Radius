"""Unit tests for dynamic confidence recalculation from test results."""

from uuid import uuid4

from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import (
    AnalysisEvidence,
    CoveragePercent,
    ImpactEvidence,
    RiskLevel,
)
from radius_confidence.domain import (
    TestEvidence as ConfidenceTestEvidence,
)
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_testing.domain import (
    TestRunResult as RadiusTestRunResult,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.dto import (
    TestRunResultResponse as RadiusTestRunResultResponse,
)


def _create_service() -> ConfidenceApplicationService:

    return ConfidenceApplicationService(
        scorer=DeterministicConfidenceScorer(),
        store=InMemoryConfidenceStore(),
    )


def test_recalculate_from_test_results_all_passed_high_score_low_risk() -> None:
    service = _create_service()
    analysis_id = uuid4()

    test_result = RadiusTestRunResultResponse(
        id=uuid4(),
        analysis_id=analysis_id,
        status="passed",
        total_tests=20,
        passed=20,
        failed=0,
        skipped=0,
        duration_ms=1500,
        coverage_percent=92.0,
        output="",
    )

    # A prior analysis mapped the single changed file to the selected tests.
    service.generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_id,
            impact=ImpactEvidence(1, 1, 1, 1, 1),
            tests=ConfidenceTestEvidence(0, 0, 0, 0, run_outcome="not_run"),
            analysis=AnalysisEvidence(changed_files=1, covered_files=("src/a.py",)),
        )
    )

    report = service.recalculate_from_test_results(analysis_id, test_result)

    assert report.analysis_id == analysis_id
    assert report.confidence_score >= 85.0
    assert report.risk_level == RiskLevel.LOW.value
    assert report.verification_status == "verified"
    assert "CI test results" in report.summary
    assert report.recommendations == ("Proceed with standard review.",)

    loaded = service.get_report(analysis_id)
    assert loaded.id == report.id
    assert loaded.confidence_score == report.confidence_score


def test_recalculate_from_test_results_with_failures_drops_score_high_risk() -> None:
    service = _create_service()
    analysis_id = uuid4()

    # Pass an entity with 6 failures
    test_result = RadiusTestRunResult(
        id=uuid4(),
        analysis_id=analysis_id,
        status=RadiusTestRunStatus.FAILED,
        total_tests=15,
        passed=8,
        failed=6,
        skipped=1,
        duration_ms=4500,
        coverage_percent=45.0,
        output="6 tests failed",
    )

    report = service.recalculate_from_test_results(analysis_id, test_result)

    assert report.analysis_id == analysis_id
    # 100 - 35 (failed > 0) - 15 (failed > 5) - 20 (coverage < 50) = 30
    assert report.confidence_score <= 50.0
    assert report.risk_level == RiskLevel.CRITICAL.value
    assert report.verification_status == "failed"
    assert "CI test results" in report.summary
    assert report.recommendations == (
        "Block merge until the failing selected tests are fixed.",
    )


def test_recalculate_from_test_results_updates_existing_report() -> None:
    service = _create_service()
    analysis_id = uuid4()

    # Initial report generated before CI run
    initial_command = GenerateConfidenceReportCommand(
        analysis_id=analysis_id,
        impact=ImpactEvidence(
            affected_files=2,
            affected_symbols=3,
            affected_modules=1,
            affected_tests=5,
            dependency_depth=1,
        ),
        tests=ConfidenceTestEvidence(
            total_tests=5,
            passed=5,
            failed=0,
            skipped=0,
            coverage_percent=CoveragePercent(88.0),
        ),
        analysis=AnalysisEvidence(changed_files=1, covered_files=("src/a.py",)),
    )
    initial_report = service.generate_report(initial_command)
    assert initial_report.confidence_score >= 85.0

    # CI run finishes with a test failure
    ci_result = RadiusTestRunResultResponse(
        id=uuid4(),
        analysis_id=analysis_id,
        status="failed",
        total_tests=5,
        passed=4,
        failed=1,
        skipped=0,
        duration_ms=800,
        coverage_percent=88.0,
        output="1 test failed",
    )

    updated_report = service.recalculate_from_test_results(analysis_id, ci_result)

    # Score dropped due to test failure (-35)
    assert updated_report.confidence_score < initial_report.confidence_score
    assert updated_report.verification_status == "failed"
    assert "CI test results" in updated_report.summary

    persisted = service.get_report(analysis_id)
    assert persisted.confidence_score == updated_report.confidence_score


def test_ci_results_without_recorded_mapping_cannot_verify() -> None:
    service = _create_service()
    analysis_id = uuid4()
    result = RadiusTestRunResultResponse(
        id=uuid4(),
        analysis_id=analysis_id,
        status="passed",
        total_tests=1,
        passed=1,
        failed=0,
        skipped=0,
        duration_ms=10,
        coverage_percent=99.0,
        output="",
    )

    report = service.recalculate_from_test_results(analysis_id, result)

    assert report.verification_status == "insufficient_evidence"
    assert report.confidence_score <= 69


def test_ci_recalculation_preserves_unmapped_files_from_analysis() -> None:
    service = _create_service()
    analysis_id = uuid4()
    service.generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_id,
            impact=ImpactEvidence(2, 2, 1, 1, 1),
            tests=ConfidenceTestEvidence(0, 0, 0, 0, run_outcome="not_run"),
            analysis=AnalysisEvidence(
                changed_files=2,
                covered_files=("src/a.py",),
                unmapped_files=("src/b.py",),
            ),
        )
    )
    result = RadiusTestRunResultResponse(
        id=uuid4(),
        analysis_id=analysis_id,
        status="passed",
        total_tests=4,
        passed=4,
        failed=0,
        skipped=0,
        duration_ms=10,
        coverage_percent=99.0,
        output="",
    )

    report = service.recalculate_from_test_results(analysis_id, result)

    assert report.verification_status == "insufficient_evidence"
    assert any(item.message == "src/b.py" for item in report.evidence)
