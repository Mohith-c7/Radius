"""Deterministic, evidence-gated confidence scoring.

Two separate outputs are produced and must not be conflated:

* ``verification_status`` -- an evidence-gated verdict. ``verified`` is only
  emitted when every executable change is mapped to selected tests, those tests
  ran to completion, and none failed. Missing evidence is never interpreted as
  passing evidence.
* ``confidence_score`` -- a 0-100 *heuristic* built from fixed penalties. It is
  NOT a calibrated probability of correctness (no outcome data has been used to
  fit it). It is capped by the verdict so that a PR without verification
  evidence can never be presented as low risk.
"""

from radius_confidence.domain.entities import (
    AnalysisEvidence,
    ConfidenceEvidence,
    ImpactEvidence,
    TestEvidence,
    TestRunOutcome,
)
from radius_confidence.domain.enums import (
    EvidenceCategory,
    EvidenceImpact,
    VerificationStatus,
)
from radius_confidence.domain.value_objects import ConfidenceScore
from radius_confidence.interfaces.scoring import ScoringResult

# Upper bounds applied to the heuristic score by verdict. With the risk
# thresholds in ConfidenceApplicationService (>=85 low, >=70 medium, >=50 high)
# an unverified change is at best "high" risk and a failing one "critical".
INSUFFICIENT_EVIDENCE_SCORE_CAP = 69.0
FAILED_SCORE_CAP = 49.0

# Evidence labels used to persist (and later reconstruct) the change-to-test
# mapping inside the existing evidence table.
LABEL_COVERED = "covered_changed_file"
LABEL_UNMAPPED = "unmapped_changed_file"
LABEL_UNANALYZED = "unanalyzed_changed_file"
LABEL_NON_EXECUTABLE = "non_executable_changed_file"
LABEL_PARSE_FAILURE = "parse_failure"
LABEL_FALLBACK = "full_suite_fallback"
LABEL_CHANGED_COUNT = "changed_files"
LABEL_VERDICT_GAP = "verdict_gap"


class DeterministicConfidenceScorer:
    """Auditable heuristic score plus an evidence-gated verdict."""

    def score(
        self,
        impact: ImpactEvidence,
        tests: TestEvidence,
        analysis: AnalysisEvidence | None = None,
    ) -> ScoringResult:
        """Return score, evidence, and decoupled confidence metrics."""

        evidence: list[ConfidenceEvidence] = [
            ConfidenceEvidence(
                category=EvidenceCategory.BLAST_RADIUS,
                label="baseline",
                message=(
                    "Heuristic score starts from 100 and subtracts fixed penalties; "
                    "it is not a calibrated probability."
                ),
                impact=EvidenceImpact.NEUTRAL,
                value=100,
            )
        ]

        score = 100.0
        nothing_to_test = analysis is not None and analysis.executable_changes <= 0
        if not nothing_to_test:
            score = self._apply_test_penalties(score, tests, evidence)
            score = self._apply_coverage_penalties(score, tests, evidence)
        score = self._apply_impact_penalties(score, impact, evidence)
        self._append_analysis_evidence(analysis, evidence)
        self._append_selected_test_evidence(tests, evidence)

        gaps = self._verification_gaps(tests, analysis)
        if tests.failed > 0:
            status = VerificationStatus.FAILED
            score = min(score, FAILED_SCORE_CAP)
        elif gaps:
            status = VerificationStatus.INSUFFICIENT_EVIDENCE
            score = min(score, INSUFFICIENT_EVIDENCE_SCORE_CAP)
        else:
            status = VerificationStatus.VERIFIED

        for gap in gaps:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.ANALYSIS,
                    label=LABEL_VERDICT_GAP,
                    message=gap,
                    impact=EvidenceImpact.NEGATIVE,
                )
            )

        final_score = ConfidenceScore(max(0.0, min(100.0, score)))
        metrics = {
            "analysis_completeness": self._completeness(analysis),
            "verification_status": status.value,
            "change_risk": "high" if impact.affected_files > 10 else "low",
            "verification_confidence": self._verification_confidence(tests),
            "verification_gaps": gaps,
        }
        return ScoringResult(final_score, tuple(evidence), metrics)

    @staticmethod
    def _verification_gaps(
        tests: TestEvidence,
        analysis: AnalysisEvidence | None,
    ) -> tuple[str, ...]:
        gaps: list[str] = []
        if analysis is None:
            gaps.append("The mapping between changed files and tests was not assessed")
            needs_tests = True
        else:
            gaps.extend(analysis.gaps)
            needs_tests = analysis.executable_changes > 0

        if tests.run_outcome == TestRunOutcome.NOT_RUN:
            if needs_tests:
                gaps.append(
                    "Selected tests were not executed; upload CI results to verify"
                )
        elif tests.run_outcome != TestRunOutcome.COMPLETED:
            detail = f" ({tests.run_detail})" if tests.run_detail else ""
            gaps.append(f"Test execution did not complete: {tests.run_outcome}{detail}")
        elif needs_tests and tests.total_tests == 0:
            gaps.append("No tests were selected or collected for the changed code")
        elif needs_tests and tests.passed == 0 and tests.failed == 0 and tests.flaky == 0:
            gaps.append("All selected tests were skipped; nothing was verified")
        if tests.flaky:
            gaps.append(
                f"{tests.flaky} flaky test(s) failed then passed on rerun; they are "
                "excluded from verification evidence"
            )
        if needs_tests and tests.selected_test_files == 0:
            gaps.append(
                "No selected test files are recorded for this analysis, so the "
                "results cannot be attributed to the changed code"
            )
        if tests.missing_selected_tests:
            gaps.append(
                f"{len(tests.missing_selected_tests)} selected test file(s) do not appear "
                "in the test results"
            )
        return tuple(gaps)

    @staticmethod
    def _append_selected_test_evidence(
        tests: TestEvidence,
        evidence: list[ConfidenceEvidence],
    ) -> None:
        if tests.selected_test_files is not None:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="selected_test_files",
                    message=(
                        f"{tests.selected_test_files} selected test file(s): "
                        f"{len(tests.executed_selected_tests)} executed, "
                        f"{len(tests.failed_selected_tests)} with failures, "
                        f"{len(tests.skipped_selected_tests)} only skipped, "
                        f"{len(tests.missing_selected_tests) - len(tests.skipped_selected_tests)}"
                        " not reported."
                    ),
                    impact=EvidenceImpact.NEUTRAL,
                    value=float(tests.selected_test_files),
                )
            )
        failed = set(tests.failed_selected_tests)
        for path in tests.executed_selected_tests:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="selected_test_failed" if path in failed else "selected_test_executed",
                    message=path,
                    impact=EvidenceImpact.NEGATIVE if path in failed else EvidenceImpact.POSITIVE,
                )
            )
        skipped = set(tests.skipped_selected_tests)
        for missing in tests.missing_selected_tests:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label=(
                        "selected_test_only_skipped"
                        if missing in skipped
                        else "selected_test_not_in_results"
                    ),
                    message=missing,
                    impact=EvidenceImpact.NEGATIVE,
                )
            )
        for name in tests.flaky_tests:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="flaky_test",
                    message=f"{name} is flaky (failed, then passed on rerun); not counted as a pass.",
                    impact=EvidenceImpact.NEGATIVE,
                )
            )
        for case in tests.contradictory_tests:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="contradictory_test_result",
                    message=f"{case} was reported as both passed and failed; counted as failed.",
                    impact=EvidenceImpact.NEGATIVE,
                )
            )

    @staticmethod
    def _completeness(analysis: AnalysisEvidence | None) -> float:
        if analysis is None:
            return 0.0
        if analysis.changed_files <= 0:
            return 100.0
        accounted = len(analysis.covered_files) + len(analysis.non_executable_files)
        return round(100.0 * accounted / analysis.changed_files, 2)

    @staticmethod
    def _verification_confidence(tests: TestEvidence) -> float:
        if tests.run_outcome != TestRunOutcome.COMPLETED or tests.total_tests == 0:
            return 0.0
        executed = tests.passed + tests.failed
        if executed == 0:
            return 0.0
        return round(100.0 * tests.passed / executed, 2)

    @staticmethod
    def _append_analysis_evidence(
        analysis: AnalysisEvidence | None,
        evidence: list[ConfidenceEvidence],
    ) -> None:
        if analysis is None:
            return
        evidence.append(
            ConfidenceEvidence(
                category=EvidenceCategory.ANALYSIS,
                label=LABEL_CHANGED_COUNT,
                message=f"{analysis.changed_files} file(s) changed in this pull request.",
                impact=EvidenceImpact.NEUTRAL,
                value=float(analysis.changed_files),
            )
        )
        groups = (
            (analysis.covered_files, LABEL_COVERED, EvidenceImpact.POSITIVE),
            (analysis.unmapped_files, LABEL_UNMAPPED, EvidenceImpact.NEGATIVE),
            (analysis.unanalyzed_files, LABEL_UNANALYZED, EvidenceImpact.NEGATIVE),
            (analysis.non_executable_files, LABEL_NON_EXECUTABLE, EvidenceImpact.NEUTRAL),
            (analysis.parse_failures, LABEL_PARSE_FAILURE, EvidenceImpact.NEGATIVE),
            (
                analysis.full_suite_fallback_reasons,
                LABEL_FALLBACK,
                EvidenceImpact.NEUTRAL,
            ),
        )
        for items, label, impact in groups:
            for item in items:
                evidence.append(
                    ConfidenceEvidence(
                        category=EvidenceCategory.ANALYSIS,
                        label=label,
                        message=item,
                        impact=impact,
                    )
                )

    def _apply_test_penalties(
        self,
        score: float,
        tests: TestEvidence,
        evidence: list[ConfidenceEvidence],
    ) -> float:
        if tests.run_outcome == TestRunOutcome.NOT_RUN:
            evidence.append(
                self._negative("tests", "Selected tests were not executed.", 25)
            )
            return score - 25
        if tests.run_outcome != TestRunOutcome.COMPLETED:
            evidence.append(
                self._negative("tests", "Test execution did not complete.", 30)
            )
            return score - 30
        if tests.total_tests == 0:
            evidence.append(self._negative("tests", "No tests were selected.", 25))
            return score - 25
        if tests.failed > 0:
            evidence.append(self._negative("tests", "At least one test failed.", 35))
            score -= 35
        if tests.failed > 5:
            evidence.append(self._negative("tests", "More than five tests failed.", 15))
            score -= 15
        if tests.skipped / tests.total_tests > 0.2:
            evidence.append(
                self._negative("tests", "More than 20% of tests skipped.", 5)
            )
            score -= 5
        if tests.failed == 0 and tests.passed > 0:
            evidence.append(
                ConfidenceEvidence(
                    category=EvidenceCategory.TESTS,
                    label="passed",
                    message=f"{tests.passed} of {tests.total_tests} selected test(s) passed.",
                    impact=EvidenceImpact.POSITIVE,
                    value=float(tests.passed),
                )
            )
        return score

    def _apply_coverage_penalties(
        self,
        score: float,
        tests: TestEvidence,
        evidence: list[ConfidenceEvidence],
    ) -> float:
        coverage = tests.coverage_percent.value if tests.coverage_percent else None
        if coverage is None:
            evidence.append(self._negative("coverage", "Coverage is missing.", 10))
            return score - 10
        if coverage < 50:
            evidence.append(self._negative("coverage", "Coverage is below 50%.", 20))
            return score - 20
        if coverage < 70:
            evidence.append(self._negative("coverage", "Coverage is below 70%.", 10))
            return score - 10
        if coverage < 85:
            evidence.append(self._negative("coverage", "Coverage is below 85%.", 5))
            return score - 5
        return score

    def _apply_impact_penalties(
        self,
        score: float,
        impact: ImpactEvidence,
        evidence: list[ConfidenceEvidence],
    ) -> float:
        if impact.affected_files > 20:
            evidence.append(
                self._negative("blast_radius", "More than 20 files affected.", 15)
            )
            score -= 15
        elif impact.affected_files > 5:
            evidence.append(
                self._negative("blast_radius", "6 to 20 files affected.", 8)
            )
            score -= 8
        if impact.affected_modules > 5:
            evidence.append(
                self._negative("blast_radius", "More than 5 modules affected.", 10)
            )
            score -= 10
        if impact.dependency_depth > 3:
            evidence.append(
                self._negative("blast_radius", "Dependency depth exceeds 3.", 10)
            )
            score -= 10
        return score

    @staticmethod
    def _negative(category: str, message: str, value: float) -> ConfidenceEvidence:
        return ConfidenceEvidence(
            category=EvidenceCategory(category),
            label=f"-{value:g}",
            message=message,
            impact=EvidenceImpact.NEGATIVE,
            value=value,
        )


def analysis_evidence_from_report_evidence(
    evidence: tuple[ConfidenceEvidence, ...],
) -> AnalysisEvidence | None:
    """Rebuild persisted change-to-test mapping from a report's evidence items.

    Returns ``None`` when the report carries no mapping (for example reports
    created before evidence gating existed), which forces re-scoring to treat
    the mapping as unassessed rather than complete.
    """

    buckets: dict[str, list[str]] = {
        LABEL_COVERED: [],
        LABEL_UNMAPPED: [],
        LABEL_UNANALYZED: [],
        LABEL_NON_EXECUTABLE: [],
        LABEL_PARSE_FAILURE: [],
        LABEL_FALLBACK: [],
    }
    changed: int | None = None
    for item in evidence:
        if item.category != EvidenceCategory.ANALYSIS:
            continue
        if item.label == LABEL_CHANGED_COUNT and item.value is not None:
            changed = int(item.value)
        elif item.label in buckets:
            buckets[item.label].append(item.message)
    if changed is None:
        return None
    return AnalysisEvidence(
        changed_files=changed,
        covered_files=tuple(buckets[LABEL_COVERED]),
        unmapped_files=tuple(buckets[LABEL_UNMAPPED]),
        unanalyzed_files=tuple(buckets[LABEL_UNANALYZED]),
        non_executable_files=tuple(buckets[LABEL_NON_EXECUTABLE]),
        parse_failures=tuple(buckets[LABEL_PARSE_FAILURE]),
        full_suite_fallback_reasons=tuple(buckets[LABEL_FALLBACK]),
    )
