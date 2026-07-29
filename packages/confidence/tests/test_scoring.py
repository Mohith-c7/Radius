"""Deterministic confidence scoring tests."""

from radius_confidence.domain import (
    CoveragePercent,
    ImpactEvidence,
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
    )

    assert score.value == 100
    assert evidence


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
