"""Confidence application service tests."""

from uuid import uuid4

import pytest
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import (
    CoveragePercent,
    ImpactEvidence,
)
from radius_confidence.domain import (
    TestEvidence as ConfidenceTestEvidence,
)
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_shared.errors import NotFoundError, ValidationError


def test_confidence_service_generates_persists_and_reads_report() -> None:
    service = _service()
    analysis_id = uuid4()

    report = service.generate_report(_command(analysis_id))
    loaded = service.get_report(analysis_id)

    assert report.id == loaded.id
    assert report.risk_level == "low"
    assert report.recommendations == ("Proceed with standard review.",)


def test_confidence_store_rejects_duplicate_report_generation() -> None:
    service = _service()
    command = _command(uuid4())
    service.generate_report(command)

    with pytest.raises(ValidationError):
        service.generate_report(command)


def test_get_report_raises_for_missing_report() -> None:
    with pytest.raises(NotFoundError):
        _service().get_report(uuid4())


def _service() -> ConfidenceApplicationService:
    return ConfidenceApplicationService(
        scorer=DeterministicConfidenceScorer(),
        store=InMemoryConfidenceStore(),
    )


def _command(analysis_id):
    return GenerateConfidenceReportCommand(
        analysis_id=analysis_id,
        impact=ImpactEvidence(
            affected_files=1,
            affected_symbols=1,
            affected_modules=1,
            affected_tests=1,
            dependency_depth=1,
        ),
        tests=ConfidenceTestEvidence(
            total_tests=5,
            passed=5,
            failed=0,
            skipped=0,
            coverage_percent=CoveragePercent(90),
        ),
    )
