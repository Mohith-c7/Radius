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


@dataclass(frozen=True, slots=True)
class PlanTestRunCommand:
    """Command to create a structured test run plan."""

    analysis_id: UUID


@dataclass(frozen=True, slots=True)
class ExecuteTestRunCommand:
    """Command to execute a planned test run."""

    analysis_id: UUID
    repository_path: Path
