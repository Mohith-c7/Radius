"""Testing application command DTOs."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DiscoverTestsCommand:
    """Command to discover tests in a repository snapshot."""

    repository_path: Path


@dataclass(frozen=True, slots=True)
class SelectTestsCommand:
    """Command to select relevant tests for changed/affected paths."""

    analysis_id: UUID
    changed_file_paths: tuple[str, ...]
    affected_file_paths: tuple[str, ...] = ()
    changed_symbols: tuple[str, ...] = ()
    # Optional evidence is normalized by the callers that own those sources.
    # Keys are test paths and values are factual descriptions from Radius.
    semantic_evidence: dict[str, tuple[str, ...]] | None = None
    coverage_evidence: dict[str, tuple[str, ...]] | None = None
    history_evidence: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True, slots=True)
class PlanTestRunCommand:
    """Command to create a structured test run plan."""

    analysis_id: UUID


@dataclass(frozen=True, slots=True)
class ExecuteTestRunCommand:
    """Command to execute a planned test run."""

    analysis_id: UUID
    repository_path: Path
