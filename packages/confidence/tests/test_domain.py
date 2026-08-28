"""Confidence domain tests."""

from uuid import uuid4

import pytest
from radius_confidence.domain import (
    ConfidenceEvidence,
    ConfidenceReport,
    ConfidenceScore,
    CoveragePercent,
    EvidenceCategory,
)


def test_score_and_coverage_validate_ranges() -> None:
    with pytest.raises(ValueError, match="Confidence score"):
        ConfidenceScore(101)

    with pytest.raises(ValueError, match="Coverage percent"):
        CoveragePercent(-1)


def test_evidence_and_report_require_content() -> None:
    with pytest.raises(ValueError, match="Evidence message cannot be empty"):
        ConfidenceEvidence(
            category=EvidenceCategory.TESTS,
            label="tests",
            message="",
        )

    with pytest.raises(ValueError, match="requires evidence"):
        ConfidenceReport(
            id=None,
            analysis_id=uuid4(),
            confidence_score=ConfidenceScore(90),
            risk_level="low",
            summary="Good",
            evidence=(),
            recommendations=("Proceed.",),
        )
