"""Analysis response DTOs."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_analysis.domain.entities import Analysis, BlastRadius, ChangedFile


@dataclass(frozen=True, slots=True)
class ChangedFileResponse:
    """Changed file response DTO."""

    id: UUID | None
    analysis_id: UUID
    path: str
    change_type: str
    additions: int
    deletions: int

    @classmethod
    def from_entity(cls, changed_file: ChangedFile) -> "ChangedFileResponse":
        """Create a response DTO from a changed-file entity."""

        return cls(
            id=changed_file.id,
            analysis_id=changed_file.analysis_id,
            path=changed_file.path.value,
            change_type=changed_file.change_type.value,
            additions=changed_file.additions,
            deletions=changed_file.deletions,
        )


@dataclass(frozen=True, slots=True)
class AnalysisResponse:
    """Analysis response DTO."""

    id: UUID | None
    repository_id: UUID
    pull_request_id: UUID
    commit_sha: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def from_entity(cls, analysis: Analysis) -> "AnalysisResponse":
        """Create a response DTO from an analysis entity."""

        return cls(
            id=analysis.id,
            repository_id=analysis.repository_id,
            pull_request_id=analysis.pull_request_id,
            commit_sha=analysis.commit_sha.value,
            status=analysis.status.value,
            started_at=analysis.started_at,
            completed_at=analysis.completed_at,
            created_at=analysis.created_at,
        )


@dataclass(frozen=True, slots=True)
class BlastRadiusResponse:
    """Blast-radius response DTO."""

    id: UUID | None
    analysis_id: UUID
    affected_files: int
    affected_symbols: int
    affected_modules: int
    affected_tests: int
    dependency_depth: int

    @classmethod
    def from_entity(cls, blast_radius: BlastRadius) -> "BlastRadiusResponse":
        """Create a response DTO from a blast-radius entity."""

        return cls(
            id=blast_radius.id,
            analysis_id=blast_radius.analysis_id,
            affected_files=blast_radius.affected_files,
            affected_symbols=blast_radius.affected_symbols,
            affected_modules=blast_radius.affected_modules,
            affected_tests=blast_radius.affected_tests,
            dependency_depth=blast_radius.dependency_depth,
        )


@dataclass(frozen=True, slots=True)
class AnalysisDetailResponse(AnalysisResponse):
    """Detailed analysis response DTO."""

    changed_files: tuple[ChangedFileResponse, ...]
    blast_radius: BlastRadiusResponse | None

    @classmethod
    def from_entity(cls, analysis: Analysis) -> "AnalysisDetailResponse":
        """Create a detailed response DTO from an analysis entity."""

        base = AnalysisResponse.from_entity(analysis)
        return cls(
            id=base.id,
            repository_id=base.repository_id,
            pull_request_id=base.pull_request_id,
            commit_sha=base.commit_sha,
            status=base.status,
            started_at=base.started_at,
            completed_at=base.completed_at,
            created_at=base.created_at,
            changed_files=tuple(
                ChangedFileResponse.from_entity(changed_file)
                for changed_file in analysis.changed_files
            ),
            blast_radius=(
                BlastRadiusResponse.from_entity(analysis.blast_radius)
                if analysis.blast_radius is not None
                else None
            ),
        )
