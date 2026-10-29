"""Tests for runtime coverage."""

from uuid import UUID, uuid4

from radius_confidence.application import CoverageApplicationService
from radius_confidence.domain import CoveragePercent
from radius_confidence.dto.commands import (
    GetCoverageForAnalysisCommand,
    GetCoverageForArtifactCommand,
    GetTestsForSymbolCommand,
    IngestCoverageCommand,
)
from radius_confidence.dto.responses import (
    CoverageArtifactResponse,
    CoverageFileResponse,
    CoverageReportResponse,
    CoverageSummaryResponse,
)
from radius_confidence.interfaces.store import CoverageStore
from radius_confidence.infrastructure.coverage_in_memory import InMemoryCoverageStore


def test_ingest_and_retrieve_coverage() -> None:
    store = InMemoryCoverageStore()
    service = CoverageApplicationService(
        scorer=None,  # type: ignore[arg-type]
        confidence_store=None,  # type: ignore[arg-type]
        coverage_store=store,
    )

    service.ingest_coverage(
        IngestCoverageCommand(
            analysis_id=uuid4(),
            framework="pytest",
            coverage_percent=88.5,
            files=[
                {
                    "test_id": uuid4(),
                    "test_path": "tests/test_core.py",
                    "path": "src/core.py",
                    "symbol": None,
                    "covered": True,
                    "count": 3,
                }
            ],
            symbols=[
                {
                    "test_id": uuid4(),
                    "file_path": "src/core.py",
                    "symbol": "process_payment",
                    "executed": True,
                    "count": 2,
                }
            ],
        )
    )

    summary = service.get_coverage_summary(
        GetCoverageForAnalysisCommand(analysis_id=uuid4())
    )
    assert summary is not None
    assert summary["coverage_percent"] == 88.5
    assert summary["artifact_count"] >= 1

    artifact = service.get_coverage_for_artifact(
        GetCoverageForArtifactCommand(
            analysis_id=uuid4(),
            path="src/core.py",
        )
    )
    assert artifact is not None


def test_ingest_and_retrieve_tests_for_symbol() -> None:
    store = InMemoryCoverageStore()
    service = CoverageApplicationService(
        scorer=None,  # type: ignore[arg-type]
        confidence_store=None,  # type: ignore[arg-type]
        coverage_store=store,
    )

    analysis_id = uuid4()
    service.ingest_coverage(
        IngestCoverageCommand(
            analysis_id=analysis_id,
            framework="jest",
            coverage_percent=None,
            files=[
                {
                    "test_id": uuid4(),
                    "test_path": "tests/test_payment.py",
                    "path": "src/payment.py",
                    "symbol": None,
                    "covered": True,
                    "count": 1,
                }
            ],
            symbols=[
                {
                    "test_id": uuid4(),
                    "file_path": "src/payment.py",
                    "symbol": "process_payment",
                    "executed": True,
                    "count": 1,
                }
            ],
        )
    )

    result = service.get_tests_for_symbol(
        GetTestsForSymbolCommand(
            analysis_id=analysis_id,
            file_path="src/payment.py",
            symbol="process_payment",
        )
    )
    assert result is not None
    assert len(result["tests"]) >= 1


def test_missing_coverage_returns_none() -> None:
    store = InMemoryCoverageStore()
    service = CoverageApplicationService(
        scorer=None,  # type: ignore[arg-type]
        confidence_store=None,  # type: ignore[arg-type]
        coverage_store=store,
    )

    summary = service.get_coverage_summary(
        GetCoverageForAnalysisCommand(analysis_id=uuid4())
    )
    assert summary is None
