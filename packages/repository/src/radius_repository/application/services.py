"""Repository application service."""

from uuid import UUID

from radius_shared.errors import NotFoundError, ValidationError

from radius_repository.domain.entities import Branch, Repository
from radius_repository.domain.enums import RepositoryStatus, RepositoryVisibility
from radius_repository.domain.value_objects import BranchName, CommitHash
from radius_repository.dto.commands import (
    ConnectRepositoryCommand,
    RepositoryListQuery,
    UpsertBranchCommand,
)
from radius_repository.dto.responses import (
    BranchResponse,
    RepositoryDetailResponse,
    RepositoryResponse,
)
from radius_repository.interfaces.repository_store import RepositoryStore


class RepositoryApplicationService:
    """Coordinates repository use cases against domain contracts."""

    def __init__(self, store: RepositoryStore) -> None:
        self._store = store

    def connect_repository(
        self,
        command: ConnectRepositoryCommand,
    ) -> RepositoryDetailResponse:
        """Connect a repository idempotently by provider repository id."""

        existing = self._store.get_by_github_repository_id(
            command.github_repository_id
        )
        if existing is not None:
            return RepositoryDetailResponse.from_entity(existing)

        repository = Repository(
            id=None,
            organization_id=command.organization_id,
            github_repository_id=command.github_repository_id,
            name=command.name,
            owner=command.owner,
            provider=command.provider,
            default_branch=BranchName(command.default_branch),
            clone_url=command.clone_url,
            visibility=command.visibility,
            status=RepositoryStatus.CONNECTED,
        )
        saved = self._store.save(repository)
        return RepositoryDetailResponse.from_entity(saved)

    def get_repository(self, repository_id: UUID) -> RepositoryDetailResponse:
        """Return a repository or raise a shared not-found error."""

        repository = self._store.get_by_id(repository_id)
        if repository is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        return RepositoryDetailResponse.from_entity(repository)

    def list_repositories(
        self,
        query: RepositoryListQuery,
    ) -> list[RepositoryResponse]:
        """Return repositories for an organization with optional filters."""

        repositories = self._store.list_by_organization(
            query.organization_id,
            status=self._parse_status(query.status),
            visibility=self._parse_visibility(query.visibility),
        )
        return [
            RepositoryResponse.from_entity(repository)
            for repository in repositories
        ]

    def disconnect_repository(self, repository_id: UUID) -> RepositoryResponse:
        """Disconnect a repository while preserving historical data."""

        if self._store.get_by_id(repository_id) is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        repository = self._store.update_status(
            repository_id,
            RepositoryStatus.DISCONNECTED,
        )
        return RepositoryResponse.from_entity(repository)

    def upsert_branch(self, command: UpsertBranchCommand) -> BranchResponse:
        """Create or update branch metadata for a connected repository."""

        repository = self._store.get_by_id(command.repository_id)
        if repository is None:
            msg = f"Repository {command.repository_id} was not found."
            raise NotFoundError(msg)

        latest_commit = (
            CommitHash(command.latest_commit_sha)
            if command.latest_commit_sha is not None
            else None
        )
        branch = Branch(
            id=None,
            repository_id=command.repository_id,
            name=BranchName(command.name),
            latest_commit=latest_commit,
        )
        saved = self._store.upsert_branch(branch)
        return BranchResponse.from_entity(saved)

    @staticmethod
    def _parse_status(status: str | None) -> RepositoryStatus | None:
        if status is None:
            return None
        try:
            return RepositoryStatus(status)
        except ValueError as exc:
            msg = f"Unsupported repository status: {status}."
            raise ValidationError(msg) from exc

    @staticmethod
    def _parse_visibility(visibility: str | None) -> RepositoryVisibility | None:
        if visibility is None:
            return None
        try:
            return RepositoryVisibility(visibility)
        except ValueError as exc:
            msg = f"Unsupported repository visibility: {visibility}."
            raise ValidationError(msg) from exc
