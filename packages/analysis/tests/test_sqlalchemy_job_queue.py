"""SQLAlchemy analysis job queue tests."""

from datetime import UTC, datetime, timedelta

from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.enums import PullRequestStatus, RepositoryVisibility
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from radius_shared.database.models import (
    AnalysisJob as AnalysisJobModel,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_sqlalchemy_job_queue_enqueues_claims_completes_and_fails() -> None:
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session)

        queue.enqueue(analysis_id)
        queue.enqueue(analysis_id)
        claimed = queue.claim_next()

        assert claimed.analysis_id == analysis_id
        assert claimed.status == "running"
        assert claimed.attempts == 1

        queue.complete(analysis_id)
        assert queue.get_by_analysis_id(analysis_id).status == "completed"

        queue.fail(analysis_id, "boom")
        assert queue.get_by_analysis_id(analysis_id).status == "failed"


def test_sqlalchemy_job_queue_recovers_stale_running_jobs() -> None:
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session, stale_after=timedelta(seconds=1))
        queue.enqueue(analysis_id)
        queue.claim_next()
        row = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        row.locked_at = datetime.now(UTC) - timedelta(minutes=5)
        session.flush()

        recovered = queue.recover_stale_jobs()

        assert recovered == 1
        assert queue.get_by_analysis_id(analysis_id).status == "pending"


def test_sqlalchemy_job_queue_requeues_until_max_attempts() -> None:
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session, max_attempts=2)
        queue.enqueue(analysis_id)
        first = queue.claim_next()

        queue.requeue(analysis_id, "temporary")
        second = queue.claim_next()
        queue.requeue(analysis_id, "permanent")

        job = queue.get_by_analysis_id(analysis_id)
        assert first.attempts == 1
        assert second.attempts == 2
        assert job.status == "failed"
        assert queue.claim_next() is None


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_analysis(session: Session):
    organization = Organization(name="Acme")
    repository = Repository(
        organization=organization,
        github_repository_id=9101,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=42,
        title="Queue analysis",
        source_branch="feature",
        target_branch="main",
        author="mohith",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    analysis = Analysis(
        repository=repository,
        pull_request=pull_request,
        commit_sha="a" * 40,
        status=db_enums.AnalysisStatus.PENDING,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, pull_request, analysis])
    session.flush()
    return analysis.id


def test_sqlalchemy_job_queue_redacts_stored_errors() -> None:
    token = "ghs_abcdefghijklmnopqrstuvwxyz0123456789"
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session, max_attempts=3)
        queue.enqueue(analysis_id)
        queue.claim_next()

        queue.requeue(analysis_id, f"clone https://x-access-token:{token}@github.com/a/b.git")

        job = queue.get_by_analysis_id(analysis_id)
        assert token not in job.last_error
        assert "[REDACTED]" in job.last_error


def test_sqlalchemy_job_queue_reenqueue_of_exhausted_job_is_claimable() -> None:
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session, max_attempts=1)
        queue.enqueue(analysis_id)
        queue.claim_next()
        queue.requeue(analysis_id, "boom")
        assert queue.get_by_analysis_id(analysis_id).status == "failed"

        queue.enqueue(analysis_id)
        claimed = queue.claim_next()

        assert claimed is not None
        assert claimed.attempts == 1


def test_sqlalchemy_job_queue_mark_analysis_failed_skips_terminal_rows() -> None:
    with _session() as session:
        analysis_id = _create_analysis(session)
        queue = SqlAlchemyAnalysisJobQueue(session)

        assert queue.mark_analysis_failed(analysis_id) is True
        analysis = session.get(Analysis, analysis_id)
        assert analysis.status == db_enums.AnalysisStatus.FAILED
        assert analysis.completed_at is not None
        assert queue.mark_analysis_failed(analysis_id) is False
