"""Cancelling queued-not-started work, and the worker skipping cancelled jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import radius_worker.runner as worker_runner
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.queue import InMemoryAnalysisQueue
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist(factory):
    with factory() as session:
        org = Organization(name="Acme", github_installation_id=1)
        repo = Repository(
            organization=org,
            github_repository_id=1,
            name="radius",
            owner="acme",
            default_branch="main",
            clone_url="https://github.com/acme/radius.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        pr = PullRequest(
            repository=repo,
            github_pr_number=1,
            title="t",
            source_branch="f",
            target_branch="main",
            author="o",
            status=db_enums.PullRequestStatus.OPEN,
            opened_at=datetime.now(UTC),
        )
        analysis = Analysis(
            repository=repo,
            pull_request=pr,
            commit_sha="a" * 40,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([org, repo, pr, analysis])
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id


def test_cancel_queued_only_cancels_unstarted_jobs() -> None:
    factory = _factory()
    analysis_id = _persist(factory)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session)
        assert queue.cancel_queued(analysis_id, "closed") is True
        job = queue.get_by_analysis_id(analysis_id)
        assert job.status == "completed" and job.last_error == "Cancelled: closed"
        # A cancelled job is never claimed.
        assert queue.claim_next() is None
        # Already finished: nothing more to cancel.
        assert queue.cancel_queued(analysis_id, "closed") is False


def test_cancel_queued_leaves_running_and_retried_jobs() -> None:
    factory = _factory()
    analysis_id = _persist(factory)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session)
        assert queue.claim_next() is not None  # now running, attempts=1
        assert queue.cancel_queued(analysis_id, "closed") is False
        queue.requeue(analysis_id, "boom")  # pending again but attempts=1
        assert queue.cancel_queued(analysis_id, "closed") is False
        assert queue.get_by_analysis_id(analysis_id).status == "pending"


def test_in_memory_queue_cancel_queued() -> None:
    from uuid import uuid4

    queue = InMemoryAnalysisQueue()
    first, second = uuid4(), uuid4()
    queue.enqueue(first)
    queue.enqueue(second)
    assert queue.cancel_queued(first, "x") is True
    assert queue.cancel_queued(first, "x") is False
    assert queue.claim_next() == second
    assert queue.cancel_queued(second, "x") is False  # already claimed


class ExplodingGit:
    def clone_or_fetch(self, *a, **k):  # pragma: no cover - must not run
        raise AssertionError("a cancelled analysis must not be cloned")


def test_worker_skips_a_claimed_job_whose_analysis_was_cancelled() -> None:
    factory = _factory()
    analysis_id = _persist(factory)
    with factory() as session:
        session.get(Analysis, analysis_id).status = db_enums.AnalysisStatus.CANCELLED
        session.commit()
    runtime = SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=ExplodingGit(),
        settings=worker_runner.WorkerSettings(GITHUB_PUBLISH_RESULTS=False),
        github_client=object(),
    )
    assert runtime.run_once() is True
    with factory() as session:
        job = session.scalar(select(AnalysisJob))
        assert job.status == db_enums.AnalysisJobStatus.COMPLETED
        assert job.last_error.startswith("Cancelled:")
        assert session.get(Analysis, analysis_id).status == db_enums.AnalysisStatus.CANCELLED
