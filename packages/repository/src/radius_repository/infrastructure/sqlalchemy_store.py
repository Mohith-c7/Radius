"""SQLAlchemy repository store adapter."""

from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.errors import NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from radius_repository.domain.entities import Branch, Repository
from radius_repository.domain.enums import (
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
                msg = f"Repository {repository.id} was not found."
                raise NotFoundError(msg)
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
