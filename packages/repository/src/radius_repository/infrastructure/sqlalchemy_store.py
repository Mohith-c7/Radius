"""SQLAlchemy repository store adapter."""

from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.errors import NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from radius_repository.domain.entities import Branch, PullRequest, Repository
from radius_repository.domain.enums import (
    PullRequestStatus,
    RepositoryProvider,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_repository.domain.value_objects import BranchName, CommitHash


class SqlAlchemyRepositoryStore:
    """Repository persistence backed by Radius SQLAlchemy models."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, repository_id: UUID) -> Repository | None:
        """Return one repository by Radius id."""

        row = self._repository_query().where(
            db_models.Repository.id == repository_id
        )
        return self._to_domain(self._session.scalar(row))

    def get_by_github_repository_id(
        self,
        github_repository_id: int,
    ) -> Repository | None:
        """Return one repository by GitHub id."""

        row = self._repository_query().where(
            db_models.Repository.github_repository_id == github_repository_id
        )
        return self._to_domain(self._session.scalar(row))

    def list_by_organization(
        self,
        organization_id: UUID,
        status: RepositoryStatus | None = None,
        visibility: RepositoryVisibility | None = None,
    ) -> list[Repository]:
        """Return repositories visible to an organization."""

        statement = self._repository_query().where(
            db_models.Repository.organization_id == organization_id
        )
        if status is not None:
            statement = statement.where(
                db_models.Repository.status == db_enums.RepositoryStatus(status.value)
            )
        if visibility is not None:
            statement = statement.where(
                db_models.Repository.visibility
                == db_enums.RepositoryVisibility(visibility.value)
            )

        rows = self._session.scalars(
            statement.order_by(db_models.Repository.created_at)
        ).all()
        return [self._to_domain(row) for row in rows if row is not None]

    def save(self, repository: Repository) -> Repository:
        """Persist a repository aggregate."""

        if repository.id is not None:
            row = self._session.get(db_models.Repository, repository.id)
            if row is None:
                row = db_models.Repository(id=repository.id)
                self._session.add(row)
        else:
            row = self._session.scalar(
                select(db_models.Repository).where(
                    db_models.Repository.github_repository_id
                    == repository.github_repository_id
                )
            )
            if row is None:
                row = db_models.Repository()
                self._session.add(row)

        row.organization_id = repository.organization_id
        row.github_repository_id = repository.github_repository_id
        row.name = repository.name
        row.owner = repository.owner
        row.provider = db_enums.RepositoryProvider(repository.provider.value)
        row.default_branch = repository.default_branch.value
        row.clone_url = repository.clone_url
        row.visibility = db_enums.RepositoryVisibility(repository.visibility.value)
        row.status = db_enums.RepositoryStatus(repository.status.value)

        self._session.flush()
        self._session.refresh(row, attribute_names=["branches"])
        domain = self._to_domain(row)
        if domain is None:
            msg = "Repository could not be saved."
            raise NotFoundError(msg)
        return domain

    def update_status(
        self,
        repository_id: UUID,
        status: RepositoryStatus,
    ) -> Repository:
        """Update repository connection status."""

        row = self._session.get(db_models.Repository, repository_id)
        if row is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        row.status = db_enums.RepositoryStatus(status.value)
        self._session.flush()
        self._session.refresh(row, attribute_names=["branches"])
        domain = self._to_domain(row)
        if domain is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)
        return domain

    def update_default_branch(
        self,
        repository_id: UUID,
        default_branch: str,
    ) -> Repository:
        """Update repository default branch."""

        row = self._session.get(db_models.Repository, repository_id)
        if row is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)

        row.default_branch = default_branch
        self._session.flush()
        self._session.refresh(row, attribute_names=["branches"])
        domain = self._to_domain(row)
        if domain is None:
            msg = f"Repository {repository_id} was not found."
            raise NotFoundError(msg)
        return domain

    def upsert_branch(self, branch: Branch) -> Branch:
        """Create or update branch metadata."""

        row = self._session.scalar(
            select(db_models.Branch).where(
                db_models.Branch.repository_id == branch.repository_id,
                db_models.Branch.name == branch.name.value,
            )
        )
        if row is None:
            row = db_models.Branch(
                repository_id=branch.repository_id,
                name=branch.name.value,
            )
            self._session.add(row)

        row.latest_commit_sha = (
            branch.latest_commit.value if branch.latest_commit else None
        )
        self._session.flush()
        self._session.refresh(row)
        return self._branch_to_domain(row)

    def get_pull_request_by_repository_and_number(
        self,
        repository_id: UUID,
        github_pr_number: int,
    ) -> PullRequest | None:
        """Return one pull request by repository and provider number."""

        row = self._session.scalar(
            select(db_models.PullRequest).where(
                db_models.PullRequest.repository_id == repository_id,
                db_models.PullRequest.github_pr_number == github_pr_number,
            )
        )
        return self._pull_request_to_domain(row) if row is not None else None

    def get_pull_request_by_id(self, pull_request_id: UUID) -> PullRequest | None:
        """Return one pull request by its Radius id."""

        row = self._session.get(db_models.PullRequest, pull_request_id)
        return self._pull_request_to_domain(row) if row is not None else None

    def list_pull_requests(self, repository_id: UUID) -> list[PullRequest]:
        """Return all pull requests for a repository ordered by opened_at desc."""

        rows = self._session.scalars(
            select(db_models.PullRequest)
            .where(db_models.PullRequest.repository_id == repository_id)
            .order_by(db_models.PullRequest.opened_at.desc())
        ).all()
        return [self._pull_request_to_domain(r) for r in rows]

    def upsert_pull_request(self, pull_request: PullRequest) -> PullRequest:
        """Create or update pull request metadata."""

        row = self._session.scalar(
            select(db_models.PullRequest).where(
                db_models.PullRequest.repository_id == pull_request.repository_id,
                db_models.PullRequest.github_pr_number
                == pull_request.github_pr_number,
            )
        )
        if row is None:
            row = db_models.PullRequest(
                repository_id=pull_request.repository_id,
                github_pr_number=pull_request.github_pr_number,
            )
            self._session.add(row)

        row.title = pull_request.title
        row.source_branch = pull_request.source_branch.value
        row.target_branch = pull_request.target_branch.value
        row.author = pull_request.author
        row.status = db_enums.PullRequestStatus(pull_request.status.value)
        row.opened_at = pull_request.opened_at
        row.merged_at = pull_request.merged_at

        self._session.flush()
        self._session.refresh(row)
        return self._pull_request_to_domain(row)

    @staticmethod
    def _repository_query():
        return select(db_models.Repository).options(
            selectinload(db_models.Repository.branches)
        )

    @classmethod
    def _to_domain(cls, row: db_models.Repository | None) -> Repository | None:
        if row is None:
            return None

        return Repository(
            id=row.id,
            organization_id=row.organization_id,
            github_repository_id=row.github_repository_id,
            name=row.name,
            owner=row.owner,
            provider=RepositoryProvider(row.provider.value),
            default_branch=BranchName(row.default_branch),
            clone_url=row.clone_url,
            visibility=RepositoryVisibility(row.visibility.value),
            status=RepositoryStatus(row.status.value),
            branches=[cls._branch_to_domain(branch) for branch in row.branches],
        )

    @staticmethod
    def _branch_to_domain(row: db_models.Branch) -> Branch:
        latest_commit = (
            CommitHash(row.latest_commit_sha)
            if row.latest_commit_sha is not None
            else None
        )
        return Branch(
            id=row.id,
            repository_id=row.repository_id,
            name=BranchName(row.name),
            latest_commit=latest_commit,
        )

    @staticmethod
    def _pull_request_to_domain(row: db_models.PullRequest) -> PullRequest:
        return PullRequest(
            id=row.id,
            repository_id=row.repository_id,
            github_pr_number=row.github_pr_number,
            title=row.title,
            source_branch=BranchName(row.source_branch),
            target_branch=BranchName(row.target_branch),
            author=row.author,
            status=PullRequestStatus(row.status.value),
            opened_at=row.opened_at,
            merged_at=row.merged_at,
        )
