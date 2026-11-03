"""In-memory repository infrastructure adapters."""

from uuid import UUID, uuid4

from radius_repository.domain.entities import Branch, PullRequest, Repository
from radius_repository.domain.enums import RepositoryStatus, RepositoryVisibility
from radius_repository.domain.value_objects import BranchName


class InMemoryRepositoryStore:
    """Repository store for local orchestration and tests."""

    def __init__(self) -> None:
        self._repositories: dict[UUID, Repository] = {}
        self._github_index: dict[int, UUID] = {}
        self._pull_requests: dict[tuple[UUID, int], PullRequest] = {}

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

    def update_default_branch(
        self,
        repository_id: UUID,
        default_branch: str,
    ) -> Repository:
        """Update repository default branch."""

        repository = self._repositories[repository_id]
        repository.default_branch = BranchName(default_branch)
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

    def get_pull_request_by_repository_and_number(
        self,
        repository_id: UUID,
        github_pr_number: int,
    ) -> PullRequest | None:
        """Return one pull request by repository and provider number."""

        return self._pull_requests.get((repository_id, github_pr_number))

    def get_pull_request_by_id(self, pull_request_id: UUID) -> PullRequest | None:
        """Return one pull request by its Radius id."""

        for pull_request in self._pull_requests.values():
            if pull_request.id == pull_request_id:
                return pull_request
        return None

    def list_pull_requests(self, repository_id: UUID) -> list[PullRequest]:
        """Return all pull requests for a repository."""

        return [
            pr
            for (r_id, _), pr in self._pull_requests.items()
            if r_id == repository_id
        ]

    def upsert_pull_request(self, pull_request: PullRequest) -> PullRequest:
        """Create or update pull request metadata."""

        key = (pull_request.repository_id, pull_request.github_pr_number)
        existing = self._pull_requests.get(key)
        saved = PullRequest(
            id=existing.id if existing is not None else uuid4(),
            repository_id=pull_request.repository_id,
            github_pr_number=pull_request.github_pr_number,
            title=pull_request.title,
            source_branch=pull_request.source_branch,
            target_branch=pull_request.target_branch,
            author=pull_request.author,
            status=pull_request.status,
            opened_at=pull_request.opened_at,
            merged_at=pull_request.merged_at,
        )
        self._pull_requests[key] = saved
        return saved
