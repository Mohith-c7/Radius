"""Confidence persistence interfaces."""

from typing import Protocol
from uuid import UUID

from radius_confidence.domain.entities import ConfidenceReport


class ConfidenceStore(Protocol):
    """Persistence contract for confidence reports."""

    def save_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Persist a confidence report."""

    def get_by_analysis_id(self, analysis_id: UUID) -> ConfidenceReport | None:
        """Return confidence report by analysis id."""

    def replace_report(self, report: ConfidenceReport) -> ConfidenceReport:
        """Replace the confidence report for an analysis (e.g. after CI ingestion)."""
