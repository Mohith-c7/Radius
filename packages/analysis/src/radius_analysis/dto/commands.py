"""Analysis application command DTOs."""

from dataclasses import dataclass
from uuid import UUID

from radius_graph.domain.entities import GraphSnapshot


@dataclass(frozen=True, slots=True)
class StartAnalysisCommand:
    """Command to create a new analysis run."""

    repository_id: UUID
    pull_request_id: UUID
    commit_sha: str


@dataclass(frozen=True, slots=True)
class RerunAnalysisCommand:
    """Command to create a new run from an existing analysis."""

    analysis_id: UUID


@dataclass(frozen=True, slots=True)
class AnalysisListQuery:
    """Query used to list analyses."""

    repository_id: UUID | None = None
    pull_request_id: UUID | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class ChangedFileInput:
    """Changed file input from a diff analyzer."""

    path: str
    change_type: str
    additions: int = 0
    deletions: int = 0


@dataclass(frozen=True, slots=True)
class RecordChangedFilesCommand:
    """Command to replace changed-file evidence for an analysis."""

    analysis_id: UUID
    changed_files: tuple[ChangedFileInput, ...]


@dataclass(frozen=True, slots=True)
class SaveBlastRadiusCommand:
    """Command to store deterministic impact summary for an analysis."""

    analysis_id: UUID
    affected_files: int = 0
    affected_symbols: int = 0
    affected_modules: int = 0
    affected_tests: int = 0
    dependency_depth: int = 0


@dataclass(frozen=True, slots=True)
class AnalyzeDiffCommand:
    """Command to parse raw git diff text into changed-file evidence."""

    analysis_id: UUID
    diff_text: str


@dataclass(frozen=True, slots=True)
class AnalyzeRepositoryDiffCommand:
    """Command to collect and parse a repository diff."""

    analysis_id: UUID
    repository_path: str
    base_ref: str
    head_ref: str


@dataclass(frozen=True, slots=True)
class ComputeBlastRadiusCommand:
    """Command to compute blast radius from graph and changed files."""

    analysis_id: UUID
    graph_snapshot: GraphSnapshot
    changed_file_paths: tuple[str, ...]
    affected_test_paths: tuple[str, ...] = ()
