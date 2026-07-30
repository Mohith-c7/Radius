"""Repository response DTOs."""

from dataclasses import dataclass
from uuid import UUID

from radius_repository.domain.entities import Branch, PullRequest, Repository


@dataclass(frozen=True, slots=True)
class BranchResponse:
    """Branch response DTO."""

    id: UUID | None
    repository_id: UUID
    name: str
    latest_commit_sha: str | None

    @classmethod
    def from_entity(cls, branch: Branch) -> "BranchResponse":
        """Create a response DTO from a branch entity."""

        return cls(
            id=branch.id,
            repository_id=branch.repository_id,
            name=branch.name.value,
            latest_commit_sha=(
                branch.latest_commit.value if branch.latest_commit else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RepositoryResponse:
    """Repository response DTO."""

    id: UUID | None
    organization_id: UUID
    github_repository_id: int
    name: str
    owner: str
    full_name: str
    provider: str
    default_branch: str
    clone_url: str
    visibility: str
    status: str

    @classmethod
    def from_entity(cls, repository: Repository) -> "RepositoryResponse":
        """Create a response DTO from a repository entity."""

        return cls(
            id=repository.id,
            organization_id=repository.organization_id,
            github_repository_id=repository.github_repository_id,
            name=repository.name,
            owner=repository.owner,
            full_name=repository.full_name,
            provider=repository.provider.value,
            default_branch=repository.default_branch.value,
            clone_url=repository.clone_url,
            visibility=repository.visibility.value,
            status=repository.status.value,
        )


@dataclass(frozen=True, slots=True)
class RepositoryDetailResponse(RepositoryResponse):
    """Detailed repository response DTO."""

    branches: tuple[BranchResponse, ...]

    @classmethod
    def from_entity(cls, repository: Repository) -> "RepositoryDetailResponse":
        """Create a detailed response DTO from a repository entity."""

        base = RepositoryResponse.from_entity(repository)
        return cls(
            id=base.id,
            organization_id=base.organization_id,
            github_repository_id=base.github_repository_id,
            name=base.name,
            owner=base.owner,
            full_name=base.full_name,
            provider=base.provider,
            default_branch=base.default_branch,
            clone_url=base.clone_url,
            visibility=base.visibility,
            status=base.status,
            branches=tuple(
                BranchResponse.from_entity(branch) for branch in repository.branches
            ),
        )


@dataclass(frozen=True, slots=True)
class PullRequestResponse:
    """Pull request response DTO."""

    id: UUID | None
    repository_id: UUID
    github_pr_number: int
    title: str
    source_branch: str
    target_branch: str
    author: str
    status: str

    @classmethod
    def from_entity(cls, pull_request: PullRequest) -> "PullRequestResponse":
        """Create a response DTO from a pull request entity."""

        return cls(
            id=pull_request.id,
            repository_id=pull_request.repository_id,
            github_pr_number=pull_request.github_pr_number,
            title=pull_request.title,
            source_branch=pull_request.source_branch.value,
            target_branch=pull_request.target_branch.value,
            author=pull_request.author,
            status=pull_request.status.value,
        )
