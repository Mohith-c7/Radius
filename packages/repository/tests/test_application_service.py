"""Repository application service tests."""

from uuid import UUID, uuid4

import pytest
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import (
    Branch,
    Repository,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_repository.dto import (
    ConnectRepositoryCommand,
    RepositoryListQuery,
    UpsertBranchCommand,
)
from radius_shared.errors import NotFoundError, ValidationError


class InMemoryRepositoryStore:
    """Small fake used to exercise service behavior."""

    def __init__(self) -> None:
        self.repositories: dict[UUID, Repository] = {}
        self.github_index: dict[int, UUID] = {}

    def get_by_id(self, repository_id: UUID) -> Repository | None:
        return self.repositories.get(repository_id)

    def get_by_github_repository_id(
        self,
        github_repository_id: int,
    ) -> Repository | None:
        repository_id = self.github_index.get(github_repository_id)
        if repository_id is None:
            return None
        return self.repositories[repository_id]

    def list_by_organization(
        self,
        organization_id: UUID,
        status: RepositoryStatus | None = None,
        visibility: RepositoryVisibility | None = None,
    ) -> list[Repository]:
        repositories = [
            repository
            for repository in self.repositories.values()
            if repository.organization_id == organization_id
        ]
        if status is not None:
            repositories = [
                repository
                for repository in repositories
                if repository.status == status
            ]
        if visibility is not None:
            repositories = [
                repository
                for repository in repositories
                if repository.visibility == visibility
            ]
        return repositories

    def save(self, repository: Repository) -> Repository:
        repository.id = repository.id or uuid4()
        self.repositories[repository.id] = repository
        self.github_index[repository.github_repository_id] = repository.id
        return repository

    def update_status(
        self,
        repository_id: UUID,
        status: RepositoryStatus,
    ) -> Repository:
        repository = self.repositories[repository_id]
        repository.status = status
        return repository

    def upsert_branch(self, branch: Branch) -> Branch:
        repository = self.repositories[branch.repository_id]
        for index, existing in enumerate(repository.branches):
            if existing.name == branch.name:
                saved = Branch(
                    id=existing.id,
                    repository_id=branch.repository_id,
                    name=branch.name,
                    latest_commit=branch.latest_commit,
                )
                repository.branches[index] = saved
                return saved

        saved = Branch(
            id=uuid4(),
            repository_id=branch.repository_id,
            name=branch.name,
            latest_commit=branch.latest_commit,
        )
        repository.branches.append(saved)
        return saved


def test_connect_repository_is_idempotent_by_github_repository_id() -> None:
    store = InMemoryRepositoryStore()
    service = RepositoryApplicationService(store)
    command = _connect_command()

    first = service.connect_repository(command)
    second = service.connect_repository(command)

    assert first.id == second.id
    assert first.full_name == "acme/radius"
    assert len(store.repositories) == 1


def test_list_repositories_filters_by_status_and_visibility() -> None:
    store = InMemoryRepositoryStore()
    service = RepositoryApplicationService(store)
    organization_id = uuid4()
    connected = service.connect_repository(
        _connect_command(
            organization_id=organization_id,
            github_repository_id=1,
            visibility=RepositoryVisibility.PRIVATE,
        )
    )
    public = service.connect_repository(
        _connect_command(
            organization_id=organization_id,
            github_repository_id=2,
            name="docs",
            visibility=RepositoryVisibility.PUBLIC,
        )
    )
    service.disconnect_repository(public.id)

    result = service.list_repositories(
        RepositoryListQuery(
            organization_id=organization_id,
            status="connected",
            visibility="private",
        )
    )

    assert [repository.id for repository in result] == [connected.id]


def test_disconnect_repository_marks_status_without_deleting() -> None:
    store = InMemoryRepositoryStore()
    service = RepositoryApplicationService(store)
    repository = service.connect_repository(_connect_command())

    disconnected = service.disconnect_repository(repository.id)

    assert disconnected.status == "disconnected"
    assert service.get_repository(repository.id).status == "disconnected"


def test_upsert_branch_creates_and_updates_branch_metadata() -> None:
    store = InMemoryRepositoryStore()
    service = RepositoryApplicationService(store)
    repository = service.connect_repository(_connect_command())

    created = service.upsert_branch(
        UpsertBranchCommand(
            repository_id=repository.id,
            name="main",
            latest_commit_sha="a" * 40,
        )
    )
    updated = service.upsert_branch(
        UpsertBranchCommand(
            repository_id=repository.id,
            name="main",
            latest_commit_sha="b" * 40,
        )
    )

    assert created.id == updated.id
    assert updated.latest_commit_sha == "b" * 40


def test_get_repository_raises_for_missing_repository() -> None:
    service = RepositoryApplicationService(InMemoryRepositoryStore())

    with pytest.raises(NotFoundError):
        service.get_repository(uuid4())


def test_list_repositories_rejects_invalid_filters() -> None:
    service = RepositoryApplicationService(InMemoryRepositoryStore())

    with pytest.raises(ValidationError):
        service.list_repositories(
            RepositoryListQuery(organization_id=uuid4(), status="archived")
        )


def _connect_command(
    *,
    organization_id: UUID | None = None,
    github_repository_id: int = 101,
    name: str = "radius",
    visibility: RepositoryVisibility = RepositoryVisibility.PRIVATE,
) -> ConnectRepositoryCommand:
    return ConnectRepositoryCommand(
        organization_id=organization_id or uuid4(),
        github_repository_id=github_repository_id,
        name=name,
        owner="acme",
        default_branch="main",
        clone_url=f"https://github.com/acme/{name}.git",
        visibility=visibility,
    )
