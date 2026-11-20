"""A worker killed mid-job (memory watchdog or host OOM) never makes its job loop forever."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import radius_worker.runner as worker_runner
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_analysis.infrastructure.sqlalchemy_job_queue import EXHAUSTED_ATTEMPTS_ERROR
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.runner import (
    KILLED_PREDECESSOR_ENV,
    SqlAlchemyWorkerRuntime,
    release_memory,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

HOST = socket.gethostname()[:60]


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist(factory) -> object:
    with factory() as session:
        org = Organization(name="Acme")
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
            github_pr_number=7,
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
            commit_sha="d" * 40,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([org, repo, pr, analysis])
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id


def _runtime(factory) -> SqlAlchemyWorkerRuntime:
    return SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=worker_runner.WorkerSettings(
            WORKER_JOB_MAX_ATTEMPTS=3, WORKER_JOB_RETRY_BASE_SECONDS=0
        ),
        github_client=object(),  # GitHub App not configured: publishing is a no-op
    )


def _claim_as(factory, pid: int):
    """Claim the job as worker process ``pid`` and mark the analysis running (then "die")."""

    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(
            session, max_attempts=3, worker_id=f"{HOST}:{pid}:abcd1234"
        )
        job = queue.claim_next()
        if job is not None:
            session.get(Analysis, job.analysis_id).status = db_enums.AnalysisStatus.RUNNING
        session.commit()
        return job


def _state(factory, analysis_id):
    with factory() as session:
        job = session.scalar(select(AnalysisJob))
        return job.status, job.attempts, job.last_error, session.get(Analysis, analysis_id).status


def _note(pid: int) -> str:
    return json.dumps({"pid": pid, "rss_mb": 412, "limit_mb": 300})


def test_killed_worker_job_is_retried_up_to_max_attempts_then_failed_with_memory_error(
    tmp_path,
) -> None:
    factory = _factory(tmp_path)
    analysis_id = _persist(factory)
    runtime = _runtime(factory)

    for attempt, pid in enumerate((4101, 4102), start=1):
        assert _claim_as(factory, pid) is not None
        assert runtime.recover_killed_predecessor(_note(pid)) == [(analysis_id, False)]
        status, attempts, error, analysis_status = _state(factory, analysis_id)
        assert status == db_enums.AnalysisJobStatus.PENDING  # retried at once, not after 30 min
        assert attempts == attempt
        assert analysis_status == db_enums.AnalysisStatus.PENDING
        assert "exceeded the memory budget" in error and "412 MB" in error

    assert _claim_as(factory, 4103) is not None
    assert runtime.recover_killed_predecessor(_note(4103)) == [(analysis_id, True)]
    status, attempts, error, analysis_status = _state(factory, analysis_id)
    assert (status, attempts) == (db_enums.AnalysisJobStatus.FAILED, 3)
    assert analysis_status == db_enums.AnalysisStatus.FAILED  # the dashboard shows it failed
    assert error.startswith("Analysis exceeded the memory budget")
    assert _claim_as(factory, 4104) is None  # never claimed again


def test_only_the_killed_process_jobs_are_released(tmp_path) -> None:
    factory = _factory(tmp_path)
    analysis_id = _persist(factory)
    runtime = _runtime(factory)
    _claim_as(factory, 412)  # a live worker whose pid starts like the killed one
    assert runtime.recover_killed_predecessor(_note(41)) == []
    status, attempts, error, _ = _state(factory, analysis_id)
    assert (status, attempts, error) == (db_enums.AnalysisJobStatus.RUNNING, 1, None)


def test_a_malformed_note_never_raises(tmp_path) -> None:
    runtime = _runtime(_factory(tmp_path))
    assert runtime.recover_killed_predecessor("not json") == []
    assert runtime.recover_killed_predecessor(json.dumps({"rss_mb": 1})) == []
    assert KILLED_PREDECESSOR_ENV == "RADIUS_WORKER_KILLED_PREDECESSOR"


def test_without_a_note_stale_lease_recovery_still_ends_in_failed(tmp_path) -> None:
    """Whole-container OOM: nobody tells the next worker; the lease expiry bounds the retries."""

    factory = _factory(tmp_path)
    analysis_id = _persist(factory)
    runtime = _runtime(factory)
    for pid in (5001, 5002, 5003):
        assert _claim_as(factory, pid) is not None
        with factory() as session:  # the worker died; its lease is never renewed
            session.scalar(select(AnalysisJob)).locked_at = datetime.now(UTC) - timedelta(hours=2)
            session.commit()
    reaped = runtime.reap_stuck_analyses()
    assert [item.analysis_id for item in reaped] == [analysis_id]
    status, attempts, error, analysis_status = _state(factory, analysis_id)
    assert (status, attempts, error) == (
        db_enums.AnalysisJobStatus.FAILED,
        3,
        EXHAUSTED_ATTEMPTS_ERROR,
    )
    assert analysis_status == db_enums.AnalysisStatus.FAILED
    assert _claim_as(factory, 5004) is None


def test_release_memory_never_raises() -> None:
    release_memory()
