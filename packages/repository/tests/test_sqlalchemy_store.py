"""SQLAlchemy repository store tests."""


from radius_repository.domain import (
    Branch,
    BranchName,
    CommitHash,
    Repository,
    RepositoryStatus,
    RepositoryVisibility,
)
from radius_repository.infrastructure import SqlAlchemyRepositoryStore
from radius_shared.database.base import Base
from radius_shared.database.models import Organization
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_store_persists_and_reads_repository() -> None:
    with _session() as session:
        organization_id = _create_organization(session)
        store = SqlAlchemyRepositoryStore(session)

        saved = store.save(_repository(organization_id=organization_id))

        assert saved.id is not None
        assert store.get_by_id(saved.id).full_name == "acme/radius"
        assert store.get_by_github_repository_id(123).id == saved.id


def test_sqlalchemy_store_lists_with_filters_and_updates_status() -> None:
    with _session() as session:
        organization_id = _create_organization(session)
        store = SqlAlchemyRepositoryStore(session)
        private_repo = store.save(
            _repository(
                organization_id=organization_id,
                github_repository_id=123,
                visibility=RepositoryVisibility.PRIVATE,
            )
        )
        store.save(
            _repository(
                organization_id=organization_id,
                github_repository_id=456,
                name="public-docs",
                visibility=RepositoryVisibility.PUBLIC,
            )
        )

        store.update_status(private_repo.id, RepositoryStatus.DISCONNECTED)
        disconnected = store.list_by_organization(
            organization_id,
            status=RepositoryStatus.DISCONNECTED,
            visibility=RepositoryVisibility.PRIVATE,
        )

        assert [repository.id for repository in disconnected] == [private_repo.id]


def test_sqlalchemy_store_upserts_branch_metadata() -> None:
    with _session() as session:
        organization_id = _create_organization(session)
        store = SqlAlchemyRepositoryStore(session)
        repository = store.save(_repository(organization_id=organization_id))

        created = store.upsert_branch(
            Branch(
                id=None,
                repository_id=repository.id,
                name=BranchName("main"),
                latest_commit=CommitHash("a" * 40),
            )
        )
        updated = store.upsert_branch(
            Branch(
                id=None,
                repository_id=repository.id,
                name=BranchName("main"),
                latest_commit=CommitHash("b" * 40),
            )
        )
        loaded = store.get_by_id(repository.id)

        assert created.id == updated.id
        assert updated.latest_commit.value == "b" * 40
        assert loaded.branches[0].latest_commit.value == "b" * 40


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_organization(session: Session):
    organization = Organization(name="Acme")
    session.add(organization)
    session.flush()
    return organization.id


def _repository(
    *,
    organization_id,
    github_repository_id: int = 123,
    name: str = "radius",
    visibility: RepositoryVisibility = RepositoryVisibility.PRIVATE,
) -> Repository:
    return Repository(
        id=None,
        organization_id=organization_id,
        github_repository_id=github_repository_id,
        name=name,
        owner="acme",
        default_branch=BranchName("main"),
        clone_url=f"https://github.com/acme/{name}.git",
        visibility=visibility,
    )
