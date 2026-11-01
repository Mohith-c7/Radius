"""In-memory analysis infrastructure adapters."""

from __future__ import annotations

from uuid import UUID, uuid4

from radius_analysis.domain.entities import Analysis, BlastRadius, ChangedFile
from radius_analysis.domain.enums import ACTIVE_ANALYSIS_STATUSES, AnalysisStatus


class InMemoryAnalysisStore:
    """Analysis store for local orchestration and tests."""

    def __init__(self) -> None:
        self._analyses: dict[UUID, Analysis] = {}

    def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Return one analysis by id."""

        return self._analyses.get(analysis_id)

    def list(
        self,
        repository_id: UUID | None = None,
        pull_request_id: UUID | None = None,
        status: AnalysisStatus | None = None,
    ) -> list[Analysis]:
        """Return analyses matching optional filters."""

        analyses = list(self._analyses.values())
        if repository_id is not None:
            analyses = [
                analysis
                for analysis in analyses
                if analysis.repository_id == repository_id
            ]
        if pull_request_id is not None:
            analyses = [
                analysis
                for analysis in analyses
                if analysis.pull_request_id == pull_request_id
            ]
        if status is not None:
            analyses = [analysis for analysis in analyses if analysis.status == status]
        return analyses

    def find_active(
        self,
        pull_request_id: UUID,
        commit_sha: str,
    ) -> Analysis | None:
        """Return a pending/running analysis for the same PR head commit."""

        for analysis in self._analyses.values():
            if (
                analysis.pull_request_id == pull_request_id
                and analysis.commit_sha.value == commit_sha
                and analysis.status in ACTIVE_ANALYSIS_STATUSES
            ):
                return analysis
        return None

    def save(self, analysis: Analysis) -> Analysis:
        """Persist an analysis in memory."""

        analysis.id = analysis.id or uuid4()
        self._analyses[analysis.id] = analysis
        return analysis

    def update_status(
        self,
        analysis_id: UUID,
        status: AnalysisStatus,
    ) -> Analysis:
        """Update analysis status."""

        analysis = self._analyses[analysis_id]
        analysis.status = status
        return analysis

    def replace_changed_files(
        self,
        analysis_id: UUID,
        changed_files: list[ChangedFile],
    ) -> list[ChangedFile]:
        """Replace changed-file evidence for an analysis."""

        saved = [
            ChangedFile(
                id=changed_file.id or uuid4(),
                analysis_id=analysis_id,
                path=changed_file.path,
                change_type=changed_file.change_type,
                additions=changed_file.additions,
                deletions=changed_file.deletions,
            )
            for changed_file in changed_files
        ]
        self._analyses[analysis_id].changed_files = saved
        return saved

    def save_blast_radius(self, blast_radius: BlastRadius) -> BlastRadius:
        """Create or replace blast-radius evidence for an analysis."""

        saved = BlastRadius(
            id=blast_radius.id or uuid4(),
            analysis_id=blast_radius.analysis_id,
            affected_files=blast_radius.affected_files,
            affected_symbols=blast_radius.affected_symbols,
            affected_modules=blast_radius.affected_modules,
            affected_tests=blast_radius.affected_tests,
            dependency_depth=blast_radius.dependency_depth,
        )
        self._analyses[blast_radius.analysis_id].blast_radius = saved
        return saved

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        """Return blast-radius evidence for one analysis."""

        return self._analyses[analysis_id].blast_radius
