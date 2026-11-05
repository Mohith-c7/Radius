"""C-02 lease ownership / heartbeat and C-05 retry backoff of the SQL job queue."""

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
from radius_shared.database.models import AnalysisJob as AnalysisJobModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def _factory(tmp_path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'queue.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _analysis(session: Session) -> object:
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
        title="t",
        source_branch="f",
        target_branch="main",
        author="a",
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


def _queue(session: Session, worker: str, **kwargs) -> SqlAlchemyAnalysisJobQueue:
    return SqlAlchemyAnalysisJobQueue(
        session, stale_after=timedelta(minutes=30), max_attempts=3, worker_id=worker, **kwargs
    )


def _expire_lease(factory, analysis_id) -> None:
    with factory() as session:
        row = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        row.locked_at = datetime.now(UTC) - timedelta(hours=1)
        session.commit()


def test_two_workers_expired_lease_only_the_owner_can_finish(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        analysis_id = _analysis(s)
        _queue(s, "w-a").enqueue(analysis_id)
        s.commit()
    with factory() as s:
        assert _queue(s, "w-a").claim_next() is not None
        s.commit()
    _expire_lease(factory, analysis_id)  # worker A is slow; its lease ran out

    with factory() as s:  # worker B recovers and re-claims the job
        job = _queue(s, "w-b").claim_next()
        s.commit()
    assert job is not None and job.claimed_by == "w-b" and job.attempts == 2

    with factory() as s:  # A finishes late: its complete/fail/requeue/heartbeat are no-ops
        qa = _queue(s, "w-a")
        assert qa.heartbeat(analysis_id) is False
        assert qa.complete(analysis_id) is False
        assert qa.fail(analysis_id, "late failure") is False
        assert qa.requeue(analysis_id, "late failure") is False
        assert qa.skip_claimed(analysis_id, "late") is False
        s.commit()
    with factory() as s:
        state = _queue(s, "w-b").get_by_analysis_id(analysis_id)
        assert state.status == "running"
        assert state.claimed_by == "w-b"
        assert state.last_error is None

    with factory() as s:  # B is the owner and completes
        assert _queue(s, "w-b").complete(analysis_id) is True
        s.commit()
    with factory() as s:
        assert _queue(s, "w-b").get_by_analysis_id(analysis_id).status == "completed"


def test_heartbeat_keeps_the_lease_from_going_stale(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        analysis_id = _analysis(s)
        _queue(s, "w-a").enqueue(analysis_id)
        _queue(s, "w-a").claim_next()
        s.commit()
    _expire_lease(factory, analysis_id)
    with factory() as s:
        assert _queue(s, "w-a").heartbeat(analysis_id) is True  # renewed in time
        s.commit()
    with factory() as s:
        assert _queue(s, "w-b").claim_next() is None  # nothing to steal
        assert _queue(s, "w-b").get_by_analysis_id(analysis_id).status == "running"


def test_heartbeat_fails_once_the_job_was_recovered_or_finished(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        analysis_id = _analysis(s)
        _queue(s, "w-a").enqueue(analysis_id)
        _queue(s, "w-a").claim_next()
        s.commit()
    _expire_lease(factory, analysis_id)
    with factory() as s:
        assert _queue(s, "w-b").recover_stale_jobs() == 1
        s.commit()
    with factory() as s:
        assert _queue(s, "w-a").heartbeat(analysis_id) is False  # now pending


def test_unguarded_queue_keeps_legacy_behaviour() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        analysis_id = _analysis(s)
        queue = SqlAlchemyAnalysisJobQueue(s)
        queue.enqueue(analysis_id)
        queue.claim_next()
        assert queue.complete(analysis_id) is True


def test_requeue_backs_off_exponentially_with_jitter(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        analysis_id = _analysis(s)
        q = _queue(s, "w-a", retry_base_seconds=100.0, retry_max_seconds=250.0)
        q.enqueue(analysis_id)
        q.claim_next()
        before = datetime.now(UTC)
        q.requeue(analysis_id, "boom")
        s.commit()
        job = q.get_by_analysis_id(analysis_id)
        wait = (job.available_at.replace(tzinfo=UTC) - before).total_seconds()
        assert job.status == "pending" and 70 <= wait <= 126  # 100 s +-25%
        assert q.claim_next() is None  # still backing off

        # Attempt 2 waits ~200 s, attempt 3 would be 400 s but is capped at 250 s.
        row = s.scalar(select(AnalysisJobModel))
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        s.flush()
        assert q.claim_next().attempts == 2
        before = datetime.now(UTC)
        q.requeue(analysis_id, "boom")
        wait2 = (q.get_by_analysis_id(analysis_id).available_at.replace(tzinfo=UTC) - before).total_seconds()
        assert 145 <= wait2 <= 251
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        s.flush()
        assert q.claim_next().attempts == 3
        q.requeue(analysis_id, "boom")  # attempts exhausted -> failed, no new retry time
        assert q.get_by_analysis_id(analysis_id).status == "failed"


def test_backoff_disabled_retries_at_once_and_analysis_returns_to_pending(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        analysis_id = _analysis(s)
        q = _queue(s, "w-a")  # retry_base_seconds defaults to 0
        q.enqueue(analysis_id)
        q.claim_next()
        analysis = s.get(Analysis, analysis_id)
        analysis.status = db_enums.AnalysisStatus.RUNNING
        s.flush()
        q.requeue(analysis_id, "boom")
        assert q.get_by_analysis_id(analysis_id).available_at is None
        assert s.get(Analysis, analysis_id).status == db_enums.AnalysisStatus.PENDING
        assert q.claim_next() is not None
