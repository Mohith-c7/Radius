"""In-memory repository infrastructure adapters."""

from uuid import UUID, uuid4

from radius_repository.domain.entities import Branch, Repository
from radius_repository.domain.enums import RepositoryStatus, RepositoryVisibility


class InMemoryRepositoryStore:
    """Repository store for local orchestration and tests."""

    def __init__(self) -> None:
        self._repositories: dict[UUID, Repository] = {}
        self._github_index: dict[int, UUID] = {}

    def get_by_id(self, repository_id: UUID) -> Repository | None:
        """Return one repository by id."""

        return self._repositories.get(repository_id)

    def get_by_github_repository_id(
        self,
        github_repository_id: int,
    ) -> Repository | None:
        """Return one repository by GitHub id."""

        repository_id = self._github_index.get(github_repository_id)
        if repository_id is None:
            return None
        return self._repositories[repository_id]

    def list_by_organization(
        self,
        organization_id: UUID,
        status: RepositoryStatus | None = None,
        visibility: RepositoryVisibility | None = None,
    ) -> list[Repository]:
        """Return repositories matching optional filters."""

        repositories = [
            repository
            for repository in self._repositories.values()
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
        """Persist a repository in memory."""

        repository.id = repository.id or uuid4()
        self._repositories[repository.id] = repository
        self._github_index[repository.github_repository_id] = repository.id
        return repository

    def update_status(
        self,
        repository_id: UUID,
        status: RepositoryStatus,
    ) -> Repository:
        """Update repository status."""

        repository = self._repositories[repository_id]
        repository.status = status
        return repository

    def upsert_branch(self, branch: Branch) -> Branch:
        """Create or update a branch."""

        repository = self._repositories[branch.repository_id]
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
