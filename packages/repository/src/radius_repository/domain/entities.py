"""Repository domain entities."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from radius_repository.domain.enums import (
    RepositoryProvider,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_repository.domain.value_objects import BranchName, CommitHash


@dataclass(frozen=True, slots=True)
class Commit:
    """Git commit metadata."""

    hash: CommitHash
    author: str
    timestamp: datetime
    message: str


@dataclass(frozen=True, slots=True)
class Branch:
    """Repository branch."""

    id: UUID | None
    repository_id: UUID
    name: BranchName
    latest_commit: CommitHash | None = None


@dataclass(slots=True)
class Repository:
    """Connected repository aggregate."""

    id: UUID | None
    organization_id: UUID
    github_repository_id: int
    name: str
    owner: str
    default_branch: BranchName
    clone_url: str
    visibility: RepositoryVisibility
    provider: RepositoryProvider = RepositoryProvider.GITHUB
    status: RepositoryStatus = RepositoryStatus.CONNECTED
    branches: list[Branch] = field(default_factory=list)

    def disconnect(self) -> None:
        """Mark the repository disconnected without deleting historical data."""

        self.status = RepositoryStatus.DISCONNECTED

    @property
    def full_name(self) -> str:
        """Return `owner/name`."""

        return f"{self.owner}/{self.name}"
