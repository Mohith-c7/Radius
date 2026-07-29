"""Repository persistence interfaces."""

from typing import Protocol
from uuid import UUID

from radius_repository.domain.entities import Branch, Repository
from radius_repository.domain.enums import RepositoryStatus, RepositoryVisibility


class RepositoryStore(Protocol):
    """Persistence contract for repository aggregates."""

    def get_by_id(self, repository_id: UUID) -> Repository | None:
        """Return one repository by Radius id."""

    def get_by_github_repository_id(
        self,
        github_repository_id: int,
    ) -> Repository | None:
        """Return one repository by GitHub id."""

    def list_by_organization(
        self,
        organization_id: UUID,
        status: RepositoryStatus | None = None,
        visibility: RepositoryVisibility | None = None,
    ) -> list[Repository]:
        """Return repositories visible to an organization."""

    def save(self, repository: Repository) -> Repository:
        """Persist a repository aggregate."""

    def update_status(
        self,
        repository_id: UUID,
        status: RepositoryStatus,
    ) -> Repository:
        """Update repository connection status."""

    def upsert_branch(self, branch: Branch) -> Branch:
        """Create or update branch metadata."""
