"""Worker failure handling: crashes, exhausted retries, stuck runs, secret hygiene."""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime, timedelta
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
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

FAKE_TOKEN = "ghs_FAKEinstallationTOKEN1234567890abcdef"
_IDS = itertools.count(1)
LEAKY_ERROR = (
    "git clone failed: fatal: could not read from "
    f"https://x-access-token:{FAKE_TOKEN}@github.com/acme/radius.git "
    f"(http.extraheader=Authorization: Bearer {FAKE_TOKEN})"
)


class LeakyGitClient:
    """Simulates a clone failure whose message echoes the credentials."""

    def __init__(self) -> None:
        self.calls = 0

    def clone_or_fetch(self, clone_url, destination, *, extra_headers=()):
        self.calls += 1
        raise RuntimeError(LEAKY_ERROR)

    def checkout(self, repository_path, branch_name):  # pragma: no cover
        raise AssertionError("checkout must not run after a failed clone")


class Token:
    def __init__(self, token: str) -> None:
        self.token = token


class FakeGitHubClient:
    def __init__(self) -> None:
        self.check_runs: list[dict] = []
        self.updated: list[dict] = []

    def create_installation_token(self, installation_id: int) -> Token:
        return Token(FAKE_TOKEN)

    def list_check_runs_for_ref(self, **kwargs):
        return []

    def create_check_run(self, **kwargs):
        self.check_runs.append(kwargs)
        return {"id": 1}

    def update_check_run(self, **kwargs):  # pragma: no cover - not exercised
        self.updated.append(kwargs)
        return {"id": kwargs["check_run_id"]}


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist_analysis(
    session_factory: sessionmaker[Session],
    *,
    status: db_enums.AnalysisStatus = db_enums.AnalysisStatus.PENDING,
    started_at: datetime | None = None,
    enqueue: bool = True,
):
    unique = next(_IDS)
    with session_factory() as session:
        organization = Organization(name=f"Acme {unique}", github_installation_id=700 + unique)
        repository = Repository(
            organization=organization,
            github_repository_id=4200 + unique,
            name="radius",
            owner="acme",
            default_branch="main",
            clone_url="https://github.com/acme/radius.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        pull_request = PullRequest(
            repository=repository,
            github_pr_number=7,
            title="Feature",
            source_branch="feature",
            target_branch="main",
            author="octocat",
            status=db_enums.PullRequestStatus.OPEN,
            opened_at=datetime.now(UTC),
        )
        analysis = Analysis(
            repository=repository,
            pull_request=pull_request,
            commit_sha="b" * 40,
            status=status,
            started_at=started_at or datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([organization, repository, pull_request, analysis])
        session.flush()
        if enqueue:
            SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id


def _runtime(
    session_factory,
    tmp_path: Path,
    github_client: FakeGitHubClient,
    **settings,
) -> SqlAlchemyWorkerRuntime:
    return SqlAlchemyWorkerRuntime(
        session_factory=session_factory,
        repository_cache_dir=tmp_path / "cache",
        git_client=LeakyGitClient(),
        settings=worker_runner.WorkerSettings(
            GITHUB_APP_ID="app-id",
            GITHUB_APP_PRIVATE_KEY="private-key",
            **settings,
        ),
        github_client=github_client,
    )


def _state(session_factory, analysis_id):
    with session_factory() as session:
        analysis = session.get(Analysis, analysis_id)
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        return analysis, job


def _run_once_expecting_failure(runtime) -> None:
    try:
        runtime.run_once()
    except RuntimeError:
        return
    raise AssertionError("run_once should re-raise the job failure")


def test_crash_on_final_attempt_fails_analysis_and_completes_check(tmp_path, caplog) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(session_factory)
    github = FakeGitHubClient()
    runtime = _runtime(session_factory, tmp_path, github, WORKER_JOB_MAX_ATTEMPTS=1)

    with caplog.at_level(logging.DEBUG):
        _run_once_expecting_failure(runtime)

    analysis, job = _state(session_factory, analysis_id)
    assert analysis.status == db_enums.AnalysisStatus.FAILED
    assert analysis.completed_at is not None
    assert job.status == db_enums.AnalysisJobStatus.FAILED
    assert FAKE_TOKEN not in job.last_error
    assert "[REDACTED]" in job.last_error
    # The GitHub check is completed (neutral), never left in progress.
    assert len(github.check_runs) == 1
    check = github.check_runs[0]
    assert check["status"] == "completed"
    assert check["conclusion"] == "neutral"
    assert check["head_sha"] == "b" * 40
    assert FAKE_TOKEN not in check["text"]
    # Structured transition logs, no secret anywhere in records or extras.
    failure_records = [r for r in caplog.records if getattr(r, "outcome", None) == "failed"]
    assert failure_records
    assert {"analysis_id", "job_id", "attempt"} <= set(vars(failure_records[0]))
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        assert FAKE_TOKEN not in str(vars(record))
    assert FAKE_TOKEN not in caplog.text


def test_non_final_crash_requeues_without_failing_analysis(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(session_factory)
    github = FakeGitHubClient()
    runtime = _runtime(session_factory, tmp_path, github, WORKER_JOB_MAX_ATTEMPTS=3)

    _run_once_expecting_failure(runtime)

    analysis, job = _state(session_factory, analysis_id)
    assert analysis.status == db_enums.AnalysisStatus.PENDING
    assert job.status == db_enums.AnalysisJobStatus.PENDING
    assert job.attempts == 1
    assert github.check_runs == []


def test_max_attempts_exhausted_marks_analysis_failed(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(session_factory)
    github = FakeGitHubClient()
    runtime = _runtime(session_factory, tmp_path, github, WORKER_JOB_MAX_ATTEMPTS=3)

    for _ in range(3):
        _run_once_expecting_failure(runtime)

    analysis, job = _state(session_factory, analysis_id)
    assert job.attempts == 3
    assert job.status == db_enums.AnalysisJobStatus.FAILED
    assert analysis.status == db_enums.AnalysisStatus.FAILED
    assert len(github.check_runs) == 1
    assert runtime.run_once() is False  # nothing left to claim


def test_run_loop_logs_and_continues_after_job_failure(tmp_path, caplog) -> None:
    session_factory = _session_factory()
    first = _persist_analysis(session_factory)
    github = FakeGitHubClient()
    runtime = _runtime(session_factory, tmp_path, github, WORKER_JOB_MAX_ATTEMPTS=2)

    with caplog.at_level(logging.WARNING):
        runtime.run_loop(poll_interval_seconds=0, stop_after_idle_cycles=1)

    analysis, job = _state(session_factory, first)
    # The loop survived both failing attempts and drained the queue.
    assert job.attempts == 2
    assert analysis.status == db_enums.AnalysisStatus.FAILED
    assert any(getattr(r, "outcome", None) == "iteration_error" for r in caplog.records)
    assert FAKE_TOKEN not in caplog.text


def test_reaper_fails_analysis_whose_stale_job_exhausted_attempts(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(session_factory, status=db_enums.AnalysisStatus.RUNNING)
    with session_factory() as session:
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        # A worker claimed the final attempt and then died (no heartbeat since).
        job.status = db_enums.AnalysisJobStatus.RUNNING
        job.attempts = 3
        job.locked_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
    github = FakeGitHubClient()
    runtime = _runtime(
        session_factory,
        tmp_path,
        github,
        WORKER_JOB_MAX_ATTEMPTS=3,
        WORKER_JOB_STALE_AFTER_SECONDS=60,
    )

    reaped = runtime.reap_stuck_analyses()

    assert [item.analysis_id for item in reaped] == [analysis_id]
    analysis, job = _state(session_factory, analysis_id)
    assert job.status == db_enums.AnalysisJobStatus.FAILED
    assert analysis.status == db_enums.AnalysisStatus.FAILED
    assert analysis.completed_at is not None
    assert github.check_runs[0]["conclusion"] == "neutral"
    assert "AnalysisStuckError" in github.check_runs[0]["text"]
    # Idempotent: a second pass finds nothing.
    assert runtime.reap_stuck_analyses() == []
    assert len(github.check_runs) == 1


def test_reaper_fails_running_analysis_past_deadline(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(
        session_factory,
        status=db_enums.AnalysisStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(hours=5),
    )
    with session_factory() as session:
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        # Still freshly locked: stale recovery alone would never end it.
        job.status = db_enums.AnalysisJobStatus.RUNNING
        job.attempts = 1
        job.locked_at = datetime.now(UTC)
        session.commit()
    fresh_id = _persist_analysis(session_factory)
    github = FakeGitHubClient()
    runtime = _runtime(
        session_factory,
        tmp_path,
        github,
        WORKER_ANALYSIS_DEADLINE_SECONDS=3600,
    )

    reaped = runtime.reap_stuck_analyses()

    assert [item.analysis_id for item in reaped] == [analysis_id]
    assert "3600s" in reaped[0].reason
    analysis, job = _state(session_factory, analysis_id)
    assert analysis.status == db_enums.AnalysisStatus.FAILED
    assert job.status == db_enums.AnalysisJobStatus.FAILED
    fresh, fresh_job = _state(session_factory, fresh_id)
    assert fresh.status == db_enums.AnalysisStatus.PENDING
    assert fresh_job.status == db_enums.AnalysisJobStatus.PENDING
    assert len(github.check_runs) == 1


def test_reaper_fails_pending_analysis_without_job_past_deadline(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(
        session_factory,
        started_at=datetime.now(UTC) - timedelta(days=1),
        enqueue=False,
    )
    runtime = _runtime(session_factory, tmp_path, FakeGitHubClient())

    reaped = runtime.reap_stuck_analyses()

    assert [(item.analysis_id, item.job_id) for item in reaped] == [(analysis_id, None)]
    analysis, _ = _state(session_factory, analysis_id)
    assert analysis.status == db_enums.AnalysisStatus.FAILED


def test_reaper_leaves_terminal_analyses_alone(tmp_path) -> None:
    session_factory = _session_factory()
    analysis_id = _persist_analysis(
        session_factory,
        status=db_enums.AnalysisStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(days=1),
    )
    runtime = _runtime(session_factory, tmp_path, FakeGitHubClient())

    assert runtime.reap_stuck_analyses() == []
    analysis, _ = _state(session_factory, analysis_id)
    assert analysis.status == db_enums.AnalysisStatus.COMPLETED
