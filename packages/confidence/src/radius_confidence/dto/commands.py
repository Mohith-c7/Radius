"""Confidence commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from radius_confidence.domain.entities import ImpactEvidence, TestEvidence


@dataclass(frozen=True)
class GenerateConfidenceReportCommand:
    """Command to generate a deterministic confidence report."""

    analysis_id: UUID
    impact: ImpactEvidence
    tests: TestEvidence


@dataclass(frozen=True)
class IngestCoverageCommand:
    """Load coverage artifacts produced by a test run."""

    analysis_id: UUID
    framework: str
    coverage_percent: float | None
    files: Iterable[dict] = ()
    symbols: Iterable[dict] = ()


@dataclass(frozen=True)
class GetCoverageForArtifactCommand:
    """Return coverage for a specific file."""

    analysis_id: UUID
    path: str


@dataclass(frozen=True)
class GetTestsForSymbolCommand:
    """Return tests that executed a specific symbol."""

    analysis_id: UUID
    file_path: str
    symbol: str


@dataclass(frozen=True)
class GetCoverageForAnalysisCommand:
    """Return aggregated coverage for an analysis."""

    analysis_id: UUID
