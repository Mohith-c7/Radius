"""Analysis domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from radius_analysis.domain.enums import AnalysisStatus, ChangedFileType
from radius_analysis.domain.value_objects import CommitSha, FilePath


@dataclass(frozen=True, slots=True)
class ChangedFile:
    """File modified during an analysis."""

    id: UUID | None
    analysis_id: UUID
    path: FilePath
    change_type: ChangedFileType
    additions: int = 0
    deletions: int = 0

    def __post_init__(self) -> None:
        if self.additions < 0:
            msg = "Changed file additions cannot be negative."
            raise ValueError(msg)
        if self.deletions < 0:
            msg = "Changed file deletions cannot be negative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BlastRadius:
    """Impact analysis summary for one analysis."""

    id: UUID | None
    analysis_id: UUID
    affected_files: int = 0
    affected_symbols: int = 0
    affected_modules: int = 0
    affected_tests: int = 0
    dependency_depth: int = 0

    def __post_init__(self) -> None:
        values = {
            "affected_files": self.affected_files,
            "affected_symbols": self.affected_symbols,
            "affected_modules": self.affected_modules,
            "affected_tests": self.affected_tests,
            "dependency_depth": self.dependency_depth,
        }
        for name, value in values.items():
            if value < 0:
                msg = f"Blast radius {name} cannot be negative."
                raise ValueError(msg)


@dataclass(slots=True)
class Analysis:
    """One Radius verification run for a pull request and commit."""

    id: UUID | None
    repository_id: UUID
    pull_request_id: UUID
    commit_sha: CommitSha
    status: AnalysisStatus = AnalysisStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    changed_files: list[ChangedFile] = field(default_factory=list)
    blast_radius: BlastRadius | None = None

    def mark_running(self) -> None:
        """Move the analysis into active execution."""

        if self.status in {AnalysisStatus.COMPLETED, AnalysisStatus.CANCELLED}:
            msg = f"Cannot run analysis with status {self.status.value}."
            raise ValueError(msg)
        self.status = AnalysisStatus.RUNNING

    def complete(self, completed_at: datetime | None = None) -> None:
        """Mark the analysis successfully completed."""

        if self.status == AnalysisStatus.CANCELLED:
            msg = "Cancelled analyses cannot be completed."
            raise ValueError(msg)
        self.status = AnalysisStatus.COMPLETED
        self.completed_at = completed_at or datetime.now(UTC)

    def fail(self, completed_at: datetime | None = None) -> None:
        """Mark the analysis failed."""

        if self.status == AnalysisStatus.CANCELLED:
            msg = "Cancelled analyses cannot be failed."
            raise ValueError(msg)
        self.status = AnalysisStatus.FAILED
        self.completed_at = completed_at or datetime.now(UTC)

    def cancel(self, completed_at: datetime | None = None) -> None:
        """Cancel the analysis."""

        if self.status == AnalysisStatus.COMPLETED:
            msg = "Completed analyses cannot be cancelled."
            raise ValueError(msg)
        self.status = AnalysisStatus.CANCELLED
        self.completed_at = completed_at or datetime.now(UTC)
