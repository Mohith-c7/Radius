"""Repository application service."""

from uuid import UUID

from radius_shared.errors import ConflictError, NotFoundError, ValidationError

from radius_repository.domain.entities import Branch, PullRequest, Repository
from radius_repository.domain.enums import (
    PullRequestStatus,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_repository.domain.value_objects import BranchName, CommitHash
from radius_repository.dto.commands import (
    ConnectRepositoryCommand,
    RepositoryListQuery,
    UpsertBranchCommand,
    UpsertPullRequestCommand,
)
from radius_repository.dto.responses import (
    BranchResponse,
    PullRequestResponse,
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
            if existing.organization_id != command.organization_id:
                # Never hand another tenant's repository (or its identifiers)
                # to the caller, and never take it over: the id is already
                # claimed. The message deliberately says nothing about who.
                msg = "This repository cannot be connected."
                raise ConflictError(msg, code="REPOSITORY_ALREADY_CONNECTED")
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

    def get_by_github_repository_id(
        self,
        github_repository_id: int,
    ) -> RepositoryDetailResponse | None:
        """Return a repository by GitHub repository id if found."""

        repository = self._store.get_by_github_repository_id(github_repository_id)
        if repository is None:
            return None
        return RepositoryDetailResponse.from_entity(repository)

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

    def reconnect_repository(self, repository_id: UUID) -> RepositoryResponse:
        """Mark a previously disconnected repository connected again."""

        if self._store.get_by_id(repository_id) is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)
        repository = self._store.update_status(
            repository_id,
            RepositoryStatus.CONNECTED,
        )
        return RepositoryResponse.from_entity(repository)

    def update_default_branch(
        self,
        repository_id: UUID,
        default_branch: str,
    ) -> RepositoryDetailResponse:
        """Update repository default branch."""

        if self._store.get_by_id(repository_id) is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        clean_branch = default_branch.strip()
        if not clean_branch:
            msg = "Default branch name cannot be empty."
            raise ValidationError(msg)

        repository = self._store.update_default_branch(repository_id, clean_branch)
        return RepositoryDetailResponse.from_entity(repository)

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

    def upsert_pull_request(
        self,
        command: UpsertPullRequestCommand,
    ) -> PullRequestResponse:
        """Create or update pull request metadata for a repository."""

        repository = self._store.get_by_id(command.repository_id)
        if repository is None:
            msg = f"Repository {command.repository_id} was not found."
            raise NotFoundError(msg)

        pull_request = PullRequest(
            id=None,
            repository_id=command.repository_id,
            github_pr_number=command.github_pr_number,
            title=command.title,
            source_branch=BranchName(command.source_branch),
            target_branch=BranchName(command.target_branch),
            author=command.author,
            status=self._parse_pull_request_status(command.status),
            opened_at=command.opened_at,
            merged_at=command.merged_at,
        )
        saved = self._store.upsert_pull_request(pull_request)
        return PullRequestResponse.from_entity(saved)

    def get_pull_request_by_repository_and_number(
        self,
        repository_id: UUID,
        github_pr_number: int,
    ) -> PullRequestResponse:
        """Return one pull request by repository and GitHub PR number."""

        pull_request = self._store.get_pull_request_by_repository_and_number(
            repository_id,
            github_pr_number,
        )
        if pull_request is None:
            msg = (
                f"Pull request {github_pr_number} for repository "
                f"{repository_id} was not found."
            )
            raise NotFoundError(msg)
        return PullRequestResponse.from_entity(pull_request)

    def pull_request_repository_id(self, pull_request_id: UUID) -> UUID | None:
        """Return the repository a pull request belongs to, or ``None`` if unknown."""

        pull_request = self._store.get_pull_request_by_id(pull_request_id)
        return pull_request.repository_id if pull_request is not None else None

    def list_pull_requests(
        self,
        repository_id: UUID,
    ) -> list[PullRequestResponse]:
        """Return all pull requests for one repository."""

        repository = self._store.get_by_id(repository_id)
        if repository is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        pull_requests = self._store.list_pull_requests(repository_id)
        return [
            PullRequestResponse.from_entity(pr) for pr in pull_requests
        ]

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

    @staticmethod
    def _parse_pull_request_status(status: str) -> PullRequestStatus:
        try:
            return PullRequestStatus(status)
        except ValueError as exc:
            msg = f"Unsupported pull request status: {status}."
            raise ValidationError(msg) from exc
