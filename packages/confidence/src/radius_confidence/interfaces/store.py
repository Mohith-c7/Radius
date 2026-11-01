"""Persistent storage interfaces for coverage and confidence evidence."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from radius_confidence.domain.entities import ConfidenceReport


class ConfidenceStore(Protocol):
    """Contract for storing and retrieving confidence reports."""

    def save_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Persist a confidence report."""

    def get_by_analysis_id(self, analysis_id: UUID) -> ConfidenceReport | None:
        """Return confidence report by analysis id."""

    def replace_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Replace the confidence report for an analysis (e.g. after CI ingestion)."""

class CoverageStore(Protocol):
    """Contract for storing and retrieving runtime coverage."""

    def ingest_coverage(
        self,
        analysis_id: UUID,
        framework: str,
        coverage_percent: float | None,
        files: Iterable[dict],
        symbols: Iterable[dict],
    ) -> None:
        """Persist coverage artifacts for one analysis."""

    def get_coverage_for_artifact(self, analysis_id: UUID, path: str) -> dict | None:
        """Return coverage for a specific source file."""

    def get_tests_for_symbol(
        self, analysis_id: UUID, file_path: str, symbol: str
    ) -> dict | None:
        """Return tests that executed a specific symbol."""

    def get_summary(self, analysis_id: UUID) -> dict | None:
        """Return aggregated coverage summary for an analysis."""

    def get_report(self, analysis_id: UUID) -> dict | None:
        """Return the full coverage report for an analysis."""
