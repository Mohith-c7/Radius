"""Repository application commands."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_repository.domain.enums import (
    RepositoryProvider,
    RepositoryVisibility,
)


@dataclass(frozen=True, slots=True)
class ConnectRepositoryCommand:
    """Command to connect a GitHub repository."""

    organization_id: UUID
    github_repository_id: int
    name: str
    owner: str
    default_branch: str
    clone_url: str
    visibility: RepositoryVisibility
    provider: RepositoryProvider = RepositoryProvider.GITHUB


@dataclass(frozen=True, slots=True)
class RepositoryListQuery:
    """Query used to list repositories for an organization."""

    organization_id: UUID
    status: str | None = None
    visibility: str | None = None


@dataclass(frozen=True, slots=True)
class UpsertBranchCommand:
    """Command to create or update branch metadata."""

    repository_id: UUID
    name: str
    latest_commit_sha: str | None = None


@dataclass(frozen=True, slots=True)
class UpsertPullRequestCommand:
    """Command to create or update pull request metadata."""

    repository_id: UUID
    github_pr_number: int
    title: str
    source_branch: str
    target_branch: str
    author: str
    status: str
    opened_at: datetime
    merged_at: datetime | None = None
