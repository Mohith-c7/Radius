"""Risk calibration while CI results are pending (production: every analysis "critical").

Before this fix a pending run cost 25 points and the insufficient-evidence cap
was 69, so every analysis waiting for CI was "high" or "critical" whatever the
change. Pending results are now a verification state ("awaiting CI"): no
penalty, a medium-risk cap, and wording that says what is missing. Gaps that
waiting cannot close keep the stricter cap.
"""

from __future__ import annotations

from uuid import uuid4

from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import (
    AnalysisEvidence,
    ImpactEvidence,
    RiskLevel,
    TestRunOutcome,
)
from radius_confidence.domain import TestEvidence as ConfidenceTestEvidence
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_confidence.infrastructure.scoring import (
    AWAITING_RESULTS_SCORE_CAP,
    INSUFFICIENT_EVIDENCE_SCORE_CAP,
)
from radius_testing.dto import TestRunResultResponse

_SMALL = ImpactEvidence(3, 5, 2, 2, 1)
_COVERED = AnalysisEvidence(
    changed_files=4,
    covered_files=(
        "apps/dashboard/lib/account-model.ts",
        "apps/dashboard/lib/auth.ts",
        "apps/dashboard/tests/account-model.test.mjs",
    ),
    non_executable_files=("changelog.d/x.fixed.md",),
)


def _pending(selected: int | None) -> ConfidenceTestEvidence:
    return ConfidenceTestEvidence(
        0, 0, 0, 0, run_outcome=TestRunOutcome.NOT_RUN, selected_test_files=selected
    )


def _service() -> ConfidenceApplicationService:
    return ConfidenceApplicationService(DeterministicConfidenceScorer(), InMemoryConfidenceStore())


def _report(impact, tests, analysis):
    service = _service()
    analysis_id = uuid4()
    report = service.generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_id, impact=impact, tests=tests, analysis=analysis
        )
    )
    return service, analysis_id, report


def test_well_mapped_change_awaiting_ci_is_medium_not_high_or_critical() -> None:
    _, _, report = _report(_SMALL, _pending(2), _COVERED)

    assert report.verification_status == "insufficient_evidence"
    assert report.risk_level == RiskLevel.MEDIUM.value
    assert report.confidence_score <= AWAITING_RESULTS_SCORE_CAP
    assert report.summary.startswith("Not verified yet: every executable change is mapped")
    assert "Awaiting CI results for 2 selected test file(s)" in report.summary
    assert not any(item.label == "-25" for item in report.evidence)
    assert any(item.label == "awaiting_results" for item in report.evidence)


def test_awaiting_ci_is_never_low_risk() -> None:
    perfect = ImpactEvidence(1, 1, 1, 1, 1)
    analysis = AnalysisEvidence(changed_files=1, covered_files=("src/a.py",))

    result = DeterministicConfidenceScorer().score(perfect, _pending(1), analysis)

    assert result.metrics["awaiting_results"] is True
    assert result[0].value == AWAITING_RESULTS_SCORE_CAP
    assert result.metrics["verification_status"] == "insufficient_evidence"


def test_real_gaps_keep_the_high_risk_cap_and_are_all_explained() -> None:
    analysis = AnalysisEvidence(
        changed_files=3,
        covered_files=("apps/dashboard/lib/api.ts",),
        unmapped_files=("apps/dashboard/app/profile/page.tsx",),
        parse_failures=("apps/dashboard/components/broken.tsx",),
    )

    _, _, report = _report(_SMALL, _pending(9), analysis)

    assert report.confidence_score <= INSUFFICIENT_EVIDENCE_SCORE_CAP
    assert report.risk_level == RiskLevel.HIGH.value
    assert "1 changed file(s) are not reached by any discovered test" in report.summary
    assert "failed to parse" in report.summary
    assert "Awaiting CI results for 9 selected test file(s)" in report.summary


def test_nothing_selected_is_not_described_as_pending() -> None:
    analysis = AnalysisEvidence(changed_files=1, unanalyzed_files=("apps/api/Dockerfile",))

    result = DeterministicConfidenceScorer().score(ImpactEvidence(0, 0, 0, 0, 0), _pending(0), analysis)

    gaps = result.metrics["verification_gaps"]
    assert "No tests were selected for the changed code" in gaps
    assert not any("not executed" in gap or "Awaiting" in gap for gap in gaps)
    assert result.metrics["awaiting_results"] is False
    assert result[0].value <= INSUFFICIENT_EVIDENCE_SCORE_CAP


def test_unknown_selection_keeps_the_strict_cap() -> None:
    analysis = AnalysisEvidence(changed_files=1, covered_files=("src/a.py",))

    result = DeterministicConfidenceScorer().score(_SMALL, _pending(None), analysis)

    assert result.metrics["awaiting_results"] is False
    assert result[0].value <= INSUFFICIENT_EVIDENCE_SCORE_CAP


def test_production_account_model_pr_is_high_not_critical() -> None:
    """Analysis 432c4bb1 after the parser fix: 3 untested UI files, 48 affected files."""

    analysis = AnalysisEvidence(
        changed_files=9,
        covered_files=(
            "apps/dashboard/lib/account-model.ts",
            "apps/dashboard/lib/api.ts",
            "apps/dashboard/lib/auth.ts",
            "apps/dashboard/tests/account-model.test.mjs",
            "apps/dashboard/tests/api.test.mjs",
        ),
        unmapped_files=(
            "apps/dashboard/app/organization/page.tsx",
            "apps/dashboard/app/profile/page.tsx",
            "apps/dashboard/components/data-panels.tsx",
        ),
        non_executable_files=("changelog.d/dashboard-real-profile-org.fixed.md",),
    )

    _, _, report = _report(ImpactEvidence(48, 300, 8, 9, 4), _pending(9), analysis)

    assert report.risk_level == RiskLevel.HIGH.value
    assert report.verification_status == "insufficient_evidence"


def _ci_result(analysis_id, *, passed: int, failed: int) -> TestRunResultResponse:
    return TestRunResultResponse(
        id=uuid4(),
        analysis_id=analysis_id,
        status="failed" if failed else "passed",
        total_tests=passed + failed,
        passed=passed,
        failed=failed,
        skipped=0,
        duration_ms=10,
        coverage_percent=None,
        output="",
    )


def test_passing_ci_upload_turns_awaiting_into_verified() -> None:
    service, analysis_id, _ = _report(_SMALL, _pending(1), _COVERED)

    report = service.recalculate_from_test_results(
        analysis_id,
        _ci_result(analysis_id, passed=5, failed=0),
        impact=_SMALL,
        selected_test_files=1,
        executed_selected_tests=("apps/dashboard/tests/account-model.test.mjs",),
    )

    assert report.verification_status == "verified"
    assert report.risk_level in {RiskLevel.LOW.value, RiskLevel.MEDIUM.value}
    assert report.summary.startswith("Verified")


def test_failing_ci_upload_is_failed_and_critical() -> None:
    service, analysis_id, _ = _report(_SMALL, _pending(1), _COVERED)

    report = service.recalculate_from_test_results(
        analysis_id,
        _ci_result(analysis_id, passed=4, failed=1),
        impact=_SMALL,
        selected_test_files=1,
        executed_selected_tests=("apps/dashboard/tests/account-model.test.mjs",),
        failed_selected_tests=("apps/dashboard/tests/account-model.test.mjs",),
    )

    assert report.verification_status == "failed"
    assert report.risk_level == RiskLevel.CRITICAL.value
