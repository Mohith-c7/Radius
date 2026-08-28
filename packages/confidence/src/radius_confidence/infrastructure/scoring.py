"""Deterministic confidence scoring."""

from radius_confidence.domain.entities import (
    ConfidenceEvidence,
    ImpactEvidence,
    TestEvidence,
)
from radius_confidence.domain.enums import EvidenceCategory, EvidenceImpact
from radius_confidence.domain.value_objects import ConfidenceScore


class DeterministicConfidenceScorer:
    """Auditable 100-point confidence scoring model."""

    def score(
        self,
        impact: ImpactEvidence,
        tests: TestEvidence,
    ) -> tuple[ConfidenceScore, tuple[ConfidenceEvidence, ...]]:
        """Return score and evidence."""

        score = 100.0
        evidence: list[ConfidenceEvidence] = [
            ConfidenceEvidence(
                category=EvidenceCategory.BLAST_RADIUS,
                label="baseline",
                message="Confidence scoring starts from 100.",
                impact=EvidenceImpact.POSITIVE,
                value=100,
            )
        ]

        score = self._apply_test_penalties(score, tests, evidence)
        score = self._apply_coverage_penalties(score, tests, evidence)
        score = self._apply_impact_penalties(score, impact, evidence)
        return ConfidenceScore(max(0, min(100, score))), tuple(evidence)

    def _apply_test_penalties(
        self,
        score: float,
        tests: TestEvidence,
        evidence: list[ConfidenceEvidence],
    ) -> float:
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
