"""Analysis persistence interfaces."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from radius_analysis.domain.entities import Analysis, BlastRadius, ChangedFile
from radius_analysis.domain.enums import AnalysisStatus


class AnalysisStore(Protocol):
    """Persistence contract for analysis runs and changed-file evidence."""

    def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Return one analysis by id."""

    def list(
        self,
        repository_id: UUID | None = None,
        pull_request_id: UUID | None = None,
        status: AnalysisStatus | None = None,
    ) -> list[Analysis]:
        """Return analyses matching optional filters."""

    def save(self, analysis: Analysis) -> Analysis:
        """Persist an analysis."""

    def update_status(
        self,
        analysis_id: UUID,
        status: AnalysisStatus,
    ) -> Analysis:
        """Update analysis status."""

    def replace_changed_files(
        self,
        analysis_id: UUID,
        changed_files: list[ChangedFile],
    ) -> list[ChangedFile]:
        """Replace changed-file evidence for an analysis."""

    def save_blast_radius(self, blast_radius: BlastRadius) -> BlastRadius:
        """Create or update blast-radius summary."""

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        """Return blast-radius summary for one analysis."""
