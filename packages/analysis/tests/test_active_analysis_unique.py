"""C-12: one active analysis per PR head commit, enforced by the schema."""

from datetime import UTC, datetime

import pytest
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, CommitSha
from radius_analysis.dto import StartAnalysisCommand
from radius_analysis.infrastructure import (
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
)
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from radius_shared.database.enums import PullRequestStatus, RepositoryVisibility
from radius_shared.database.models import Organization, PullRequest, Repository
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

SHA = "e" * 40


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'a.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _context(factory):
    with factory() as session:
        org = Organization(name="Acme")
        repo = Repository(
            organization=org,
            github_repository_id=1,
            name="r",
            owner="o",
            default_branch="main",
            clone_url="https://github.com/o/r.git",
            visibility=RepositoryVisibility.PRIVATE,
        )
        pr = PullRequest(
            repository=repo,
            github_pr_number=1,
            title="t",
            source_branch="f",
            target_branch="main",
            author="a",
            status=PullRequestStatus.OPEN,
            opened_at=datetime.now(UTC),
        )
        session.add_all([org, repo, pr])
        session.commit()
        return repo.id, pr.id


def _new(repo_id, pr_id, status=AnalysisStatus.PENDING) -> Analysis:
    return Analysis(
        id=None,
        repository_id=repo_id,
        pull_request_id=pr_id,
        commit_sha=CommitSha(SHA),
        status=status,
    )


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(db_models.Analysis))


def test_database_rejects_a_second_active_analysis_for_one_head_commit(factory) -> None:
    repo_id, pr_id = _context(factory)
    with factory() as session:
        for _ in range(2):
            session.add(
                db_models.Analysis(
                    repository_id=repo_id,
                    pull_request_id=pr_id,
                    commit_sha=SHA,
                    status=db_models.AnalysisStatus.PENDING,
                    started_at=datetime.now(UTC),
                    created_at=datetime.now(UTC),
                )
            )
        with pytest.raises(IntegrityError):
            session.flush()


def test_store_returns_the_existing_active_analysis_when_the_insert_loses_the_race(
    factory,
) -> None:
    repo_id, pr_id = _context(factory)
    with factory() as winner, factory() as loser:
        first = SqlAlchemyAnalysisStore(winner).save(_new(repo_id, pr_id))
        winner.commit()
        # The loser's check-then-insert already passed before the winner committed:
        # call save() directly, bypassing find_active.
        second = SqlAlchemyAnalysisStore(loser).save(_new(repo_id, pr_id))
        loser.commit()
        assert second.id == first.id
        assert _count(loser) == 1


def test_service_does_not_create_a_second_job_for_the_duplicate(factory) -> None:
    repo_id, pr_id = _context(factory)
    command = StartAnalysisCommand(
        repository_id=repo_id, pull_request_id=pr_id, commit_sha=SHA
    )
    ids = []
    for _ in range(2):
        with factory() as session:
            service = AnalysisApplicationService(
                SqlAlchemyAnalysisStore(session),
                pipeline=SqlAlchemyAnalysisJobQueue(session),
            )
            # force=True skips the find_active pre-check (a rerun or a lost race).
            ids.append(service.start_analysis(command, force=True).id)
            session.commit()
    assert ids[0] == ids[1]
    with factory() as session:
        assert _count(session) == 1
        assert session.scalar(select(func.count()).select_from(db_models.AnalysisJob)) == 1


def test_a_finished_analysis_can_be_rerun(factory) -> None:
    repo_id, pr_id = _context(factory)
    with factory() as session:
        store = SqlAlchemyAnalysisStore(session)
        first = store.save(_new(repo_id, pr_id))
        store.update_status(first.id, AnalysisStatus.COMPLETED)
        second = store.save(_new(repo_id, pr_id))
        session.commit()
        assert second.id != first.id
        assert _count(session) == 2


def test_store_pages_and_lists_many_repositories_in_a_constant_number_of_queries(tmp_path) -> None:
    """C-11: one filtered, limited query (plus two eager loads) however many repositories."""

    from radius_analysis.dto import AnalysisListQuery
    from sqlalchemy import event

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repo_ids = []
    with factory() as session:
        org = Organization(name="Acme")
        session.add(org)
        for n in range(6):
            repo = Repository(
                organization=org,
                github_repository_id=100 + n,
                name=f"r{n}",
                owner="o",
                default_branch="main",
                clone_url="https://github.com/o/r.git",
                visibility=RepositoryVisibility.PRIVATE,
            )
            pr = PullRequest(
                repository=repo,
                github_pr_number=1,
                title="t",
                source_branch="f",
                target_branch="main",
                author="a",
                status=PullRequestStatus.OPEN,
                opened_at=datetime.now(UTC),
            )
            session.add_all([repo, pr])
            session.flush()
            repo_ids.append(repo.id)
            for k in range(3):
                SqlAlchemyAnalysisStore(session).save(
                    Analysis(
                        id=None,
                        repository_id=repo.id,
                        pull_request_id=pr.id,
                        commit_sha=CommitSha(f"{k}" * 40),
                        status=AnalysisStatus.COMPLETED,
                    )
                )
        session.commit()

    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    with factory() as session:
        service = AnalysisApplicationService(SqlAlchemyAnalysisStore(session))
        query = AnalysisListQuery(repository_ids=tuple(repo_ids), limit=5, offset=2)
        page = service.list_analyses(query)
        assert len(page) == 5
        assert service.count_analyses(query) == 18
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 4, selects  # analyses + 2 eager loads + count, not 6 repositories x 3
