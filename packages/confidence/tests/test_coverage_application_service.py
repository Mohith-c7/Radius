"""Application-level coverage tests."""

from uuid import uuid4

from radius_confidence.application import CoverageApplicationService
from radius_confidence.dto.commands import (
    GetCoverageForAnalysisCommand,
    IngestCoverageCommand,
)
from radius_confidence.dto.responses import CoverageReportResponse
from radius_confidence.infrastructure.coverage_in_memory import InMemoryCoverageStore


def test_ingest_coverage_updates_summary_and_report() -> None:
    coverage_store = InMemoryCoverageStore()
    service = CoverageApplicationService(
        scorer=None,  # type: ignore[arg-type]
        confidence_store=None,  # type: ignore[arg-type]
        coverage_store=coverage_store,
    )

    analysis_id = uuid4()
    service.ingest_coverage(
        IngestCoverageCommand(
            analysis_id=analysis_id,
            framework="pytest",
            coverage_percent=92.0,
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
        GetCoverageForAnalysisCommand(analysis_id=analysis_id)
    )
    assert summary is not None
    assert summary["coverage_percent"] == 92.0

    report = service.get_coverage_report(
        GetCoverageForAnalysisCommand(analysis_id=analysis_id)
    )
    assert isinstance(report, CoverageReportResponse)
    assert report.analysis_id == analysis_id
