"""Deterministic confidence scoring tests."""

from radius_confidence.domain import (
    AnalysisEvidence,
    CoveragePercent,
    ImpactEvidence,
    TestRunOutcome,
)
from radius_confidence.domain import (
    TestEvidence as ConfidenceTestEvidence,
)
from radius_confidence.infrastructure import DeterministicConfidenceScorer


def test_perfect_evidence_scores_low_risk_range() -> None:
    score, evidence = DeterministicConfidenceScorer().score(
        ImpactEvidence(
            affected_files=1,
            affected_symbols=1,
            affected_modules=1,
            affected_tests=1,
            dependency_depth=1,
        ),
        ConfidenceTestEvidence(
            total_tests=10,
            passed=10,
            failed=0,
            skipped=0,
            coverage_percent=CoveragePercent(90),
        ),
        AnalysisEvidence(changed_files=1, covered_files=("src/a.py",)),
    )

    assert score.value == 100
    assert evidence


_SMALL_IMPACT = ImpactEvidence(1, 1, 1, 1, 1)
_ALL_PASSED = ConfidenceTestEvidence(10, 10, 0, 0, CoveragePercent(95))


def test_passing_tests_without_mapping_evidence_are_never_verified() -> None:
    result = DeterministicConfidenceScorer().score(_SMALL_IMPACT, _ALL_PASSED)

    assert result.metrics["verification_status"] == "insufficient_evidence"
    assert result[0].value <= 69


def test_unmapped_changed_file_blocks_verification_even_if_tests_pass() -> None:
    result = DeterministicConfidenceScorer().score(
        _SMALL_IMPACT,
        _ALL_PASSED,
        AnalysisEvidence(
            changed_files=2,
            covered_files=("src/a.py",),
            unmapped_files=("src/b.py",),
        ),
    )

    assert result.metrics["verification_status"] == "insufficient_evidence"
    assert result.metrics["analysis_completeness"] == 50.0
    assert result[0].value <= 69
    assert any(item.message == "src/b.py" for item in result[1])


def test_unanalyzed_and_parse_failures_block_verification() -> None:
    for analysis in (
        AnalysisEvidence(changed_files=1, unanalyzed_files=("db/schema.sql",)),
        AnalysisEvidence(
            changed_files=1,
            covered_files=("src/a.py",),
            parse_failures=("src/broken.py",),
        ),
    ):
        result = DeterministicConfidenceScorer().score(
            _SMALL_IMPACT, _ALL_PASSED, analysis
        )
        assert result.metrics["verification_status"] == "insufficient_evidence"


def test_incomplete_or_missing_runs_are_not_treated_as_passing() -> None:
    covered = AnalysisEvidence(changed_files=1, covered_files=("src/a.py",))
    for tests in (
        ConfidenceTestEvidence(0, 0, 0, 0, run_outcome=TestRunOutcome.NOT_RUN),
        ConfidenceTestEvidence(3, 0, 0, 0, run_outcome=TestRunOutcome.ERROR),
        ConfidenceTestEvidence(3, 0, 0, 0, run_outcome=TestRunOutcome.TIMEOUT),
        ConfidenceTestEvidence(3, 0, 0, 3),
        ConfidenceTestEvidence(0, 0, 0, 0),
    ):
        result = DeterministicConfidenceScorer().score(_SMALL_IMPACT, tests, covered)
        assert result.metrics["verification_status"] == "insufficient_evidence", tests
        assert result[0].value <= 69


def test_failing_test_is_failed_verdict_with_critical_cap() -> None:
    result = DeterministicConfidenceScorer().score(
        _SMALL_IMPACT,
        ConfidenceTestEvidence(10, 9, 1, 0, CoveragePercent(95)),
        AnalysisEvidence(changed_files=1, covered_files=("src/a.py",)),
    )

    assert result.metrics["verification_status"] == "failed"
    assert result[0].value <= 49


def test_docs_only_change_is_verified_without_tests() -> None:
    result = DeterministicConfidenceScorer().score(
        ImpactEvidence(0, 0, 0, 0, 0),
        ConfidenceTestEvidence(0, 0, 0, 0, run_outcome=TestRunOutcome.NOT_RUN),
        AnalysisEvidence(changed_files=1, non_executable_files=("README.md",)),
    )

    assert result.metrics["verification_status"] == "verified"
    assert result[0].value == 100


def test_failed_tests_low_coverage_and_large_impact_reduce_score() -> None:
    score, evidence = DeterministicConfidenceScorer().score(
        ImpactEvidence(
            affected_files=25,
            affected_symbols=5,
            affected_modules=6,
            affected_tests=10,
            dependency_depth=4,
        ),
        ConfidenceTestEvidence(
            total_tests=10,
            passed=2,
            failed=6,
            skipped=3,
            coverage_percent=CoveragePercent(45),
        ),
    )

    assert score.value == 0
    assert any(item.message == "More than five tests failed." for item in evidence)
    assert any(item.message == "Coverage is below 50%." for item in evidence)


def test_missing_tests_and_coverage_are_penalized_deterministically() -> None:
    scorer = DeterministicConfidenceScorer()
    input_impact = ImpactEvidence(0, 0, 0, 0, 0)
    input_tests = ConfidenceTestEvidence(0, 0, 0, 0, None)

    first, _ = scorer.score(input_impact, input_tests)
    second, _ = scorer.score(input_impact, input_tests)

    assert first.value == 65
    assert second.value == first.value
