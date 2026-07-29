"""SQLAlchemy analysis store tests."""

from datetime import UTC, datetime

from radius_analysis.domain import (
    Analysis,
    AnalysisStatus,
    BlastRadius,
    ChangedFile,
    ChangedFileType,
    CommitSha,
    FilePath,
)
from radius_analysis.infrastructure import SqlAlchemyAnalysisStore
from radius_shared.database.base import Base
from radius_shared.database.enums import PullRequestStatus, RepositoryVisibility
from radius_shared.database.models import Organization, PullRequest, Repository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_store_persists_and_reads_analysis() -> None:
    with _session() as session:
        repository_id, pull_request_id = _create_repository_context(session)
        store = SqlAlchemyAnalysisStore(session)

        saved = store.save(_analysis(repository_id, pull_request_id))

        assert saved.id is not None
        assert store.get_by_id(saved.id).commit_sha.value == "a" * 40


def test_sqlalchemy_store_lists_and_updates_status() -> None:
    with _session() as session:
        repository_id, pull_request_id = _create_repository_context(session)
        store = SqlAlchemyAnalysisStore(session)
        pending = store.save(_analysis(repository_id, pull_request_id))
        running = store.save(_analysis(repository_id, pull_request_id, commit="b" * 40))

        store.update_status(running.id, AnalysisStatus.RUNNING)
        result = store.list(repository_id=repository_id, status=AnalysisStatus.PENDING)

        assert [analysis.id for analysis in result] == [pending.id]


def test_sqlalchemy_store_replaces_changed_files_and_saves_blast_radius() -> None:
    with _session() as session:
        repository_id, pull_request_id = _create_repository_context(session)
        store = SqlAlchemyAnalysisStore(session)
        analysis = store.save(_analysis(repository_id, pull_request_id))

        store.replace_changed_files(
            analysis.id,
            [
                ChangedFile(
                    id=None,
                    analysis_id=analysis.id,
                    path=FilePath("src/app.py"),
                    change_type=ChangedFileType.MODIFIED,
                    additions=4,
                    deletions=2,
                )
            ],
        )
        store.replace_changed_files(
            analysis.id,
            [
                ChangedFile(
                    id=None,
                    analysis_id=analysis.id,
                    path=FilePath("src/domain.py"),
                    change_type=ChangedFileType.ADDED,
                    additions=8,
                )
            ],
        )
        blast_radius = store.save_blast_radius(
            BlastRadius(
                id=None,
                analysis_id=analysis.id,
                affected_files=3,
                affected_symbols=2,
                affected_modules=1,
                affected_tests=4,
                dependency_depth=2,
            )
        )
        loaded = store.get_by_id(analysis.id)

        assert [changed_file.path.value for changed_file in loaded.changed_files] == [
            "src/domain.py"
        ]
        assert blast_radius.affected_files == 3
        assert loaded.blast_radius.dependency_depth == 2


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_repository_context(session: Session):
    organization = Organization(name="Acme")
    repository = Repository(
        organization=organization,
        github_repository_id=9001,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=42,
        title="Add analysis lifecycle",
        source_branch="feature/analysis",
        target_branch="main",
        author="mohith",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, pull_request])
    session.flush()
    return repository.id, pull_request.id


def _analysis(repository_id, pull_request_id, commit: str = "a" * 40) -> Analysis:
    return Analysis(
        id=None,
        repository_id=repository_id,
        pull_request_id=pull_request_id,
        commit_sha=CommitSha(commit),
    )
