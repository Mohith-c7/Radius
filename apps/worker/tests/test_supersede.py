"""Superseded pull request analyses: cancelled when queued, stopped when running."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import radius_worker.runner as worker_runner
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
)
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    ConfidenceReport,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.orchestrator import ExecuteAnalysisCommand
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

OLD, NEW = "a" * 40, "b" * 40
_IDS = itertools.count(1)


class Token:
    token = "ghs_test"


class FakeGitHubClient:
    """Stateful like GitHub: one check run per (head sha, name), updated in place."""

    def __init__(self) -> None:
        self.check_runs: list[dict] = []

    def create_installation_token(self, installation_id: int) -> Token:
        return Token()

    def list_check_runs_for_ref(self, *, ref, check_name, **_):
        return [r for r in self.check_runs if r["head_sha"] == ref and r["name"] == check_name]

    def create_check_run(self, **kwargs):
        run = {**kwargs, "id": len(self.check_runs) + 1}
        self.check_runs.append(run)
        return run

    def update_check_run(self, *, check_run_id, **kwargs):
        run = next(r for r in self.check_runs if r["id"] == check_run_id)
        run.update(kwargs)
        return run


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist(factory, *, commit_sha=OLD, pull_request=True, created_at=None):
    """One analysis (with a queued job); a second call reuses the org/repo/PR."""

    with factory() as session:
        repository = session.scalar(select(Repository))
        if repository is None:
            unique = next(_IDS)
            organization = Organization(name=f"Acme {unique}", github_installation_id=900)
            repository = Repository(
                organization=organization,
                github_repository_id=5100 + unique,
                name="radius",
                owner="acme",
                default_branch="main",
                clone_url="https://github.com/acme/radius.git",
                visibility=db_enums.RepositoryVisibility.PRIVATE,
                status=db_enums.RepositoryStatus.CONNECTED,
            )
            session.add_all(
                [
                    organization,
                    repository,
                    PullRequest(
                        repository=repository,
                        github_pr_number=7,
                        title="Feature",
                        source_branch="feature",
                        target_branch="main",
                        author="octocat",
                        status=db_enums.PullRequestStatus.OPEN,
                        opened_at=datetime.now(UTC),
                    ),
                ]
            )
            session.flush()
        pr = session.scalar(select(PullRequest)) if pull_request else None
        analysis = Analysis(
            repository_id=repository.id,
            pull_request_id=pr.id if pr is not None else None,
            commit_sha=commit_sha,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=created_at or datetime.now(UTC),
        )
        session.add(analysis)
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id, (pr.id if pr is not None else None)


def _state(factory, analysis_id):
    with factory() as session:
        analysis = session.get(Analysis, analysis_id)
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        return analysis.status, job.status, job.last_error


def _service(session) -> AnalysisApplicationService:
    return AnalysisApplicationService(
        SqlAlchemyAnalysisStore(session), pipeline=SqlAlchemyAnalysisJobQueue(session)
    )


# -- queue -----------------------------------------------------------------------------


def test_request_cancel_cancels_queued_and_flags_started_jobs() -> None:
    factory = _factory()
    queued, _ = _persist(factory)
    running, _ = _persist(factory, commit_sha="c" * 40)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session, worker_id="w1", retry_base_seconds=60)
        # Oldest job first: claim ``queued`` then release it again as a (later) retry.
        assert queue.claim_next().analysis_id == queued
        assert queue.requeue(queued, "boom") is True  # pending retry, attempts=1
        assert queue.claim_next().analysis_id == running
        session.commit()
    with factory() as session:
        api_queue = SqlAlchemyAnalysisJobQueue(session)
        assert api_queue.request_cancel(running, "Superseded.") == "requested"
        assert api_queue.request_cancel(queued, "Superseded.") == "requested"
        assert api_queue.cancel_requested(running) == "Superseded."
        session.commit()
    # The running job is only flagged: the worker still owns it.
    assert _state(factory, running)[1] == db_enums.AnalysisJobStatus.RUNNING
    with factory() as session:
        session.scalar(
            select(AnalysisJob).where(AnalysisJob.analysis_id == queued)
        ).available_at = None
        worker_queue = SqlAlchemyAnalysisJobQueue(session, worker_id="w2")
        claimed = worker_queue.claim_next()
        # The claim keeps the request, so the worker can skip the retry.
        assert claimed.analysis_id == queued
        assert claimed.last_error == "Cancelled: Superseded."


def test_request_cancel_on_a_never_started_job_cancels_it_outright() -> None:
    factory = _factory()
    queued, _ = _persist(factory)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session)
        assert queue.request_cancel(queued, "Superseded.") == "cancelled"
        assert queue.request_cancel(queued, "Superseded.") == "none"  # already finished
        assert queue.cancel_requested(queued) is None
        session.commit()
    assert _state(factory, queued)[1:] == (
        db_enums.AnalysisJobStatus.COMPLETED,
        "Cancelled: Superseded.",
    )


def test_stale_recovery_finishes_a_job_whose_cancel_was_requested() -> None:
    factory = _factory()
    analysis_id, _ = _persist(factory)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session, worker_id="dead")
        queue.claim_next()
        session.get(Analysis, analysis_id).status = db_enums.AnalysisStatus.RUNNING
        queue.request_cancel(analysis_id, "Superseded.")
        job = session.scalar(select(AnalysisJob))
        job.locked_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
    with factory() as session:
        SqlAlchemyAnalysisJobQueue(session, stale_after=timedelta(minutes=5)).recover_stale_jobs()
        session.commit()
    assert _state(factory, analysis_id) == (
        db_enums.AnalysisStatus.CANCELLED,
        db_enums.AnalysisJobStatus.COMPLETED,
        "Cancelled: Superseded.",
    )


# -- service ---------------------------------------------------------------------------


def test_cancel_superseded_only_touches_older_heads_of_the_same_pull_request() -> None:
    factory = _factory()
    old, pr_id = _persist(factory, commit_sha=OLD)
    other_old, _ = _persist(factory, commit_sha="c" * 40)
    manual, _ = _persist(factory, commit_sha=OLD, pull_request=False)
    head, _ = _persist(factory, commit_sha=NEW)
    with factory() as session:
        cancelled = _service(session).cancel_superseded(
            pull_request_id=pr_id, head_sha=NEW, superseded_shas=(OLD.upper(),)
        )
        session.commit()
    assert cancelled == [old]
    assert _state(factory, old)[0] == db_enums.AnalysisStatus.CANCELLED
    assert _state(factory, old)[2].startswith("Cancelled: Superseded by a newer commit")
    # Not named, a manual (no pull request) analysis, and the head itself: untouched.
    for untouched in (other_old, manual, head):
        assert _state(factory, untouched)[0] == db_enums.AnalysisStatus.PENDING

    with factory() as session:  # ``None`` = every other commit of the pull request
        assert _service(session).cancel_superseded(pull_request_id=pr_id, head_sha=NEW) == [
            other_old
        ]
        session.commit()
    assert _state(factory, manual)[0] == db_enums.AnalysisStatus.PENDING
    assert _state(factory, head)[0] == db_enums.AnalysisStatus.PENDING


def test_cancel_superseded_flags_a_running_analysis_without_touching_its_row() -> None:
    factory = _factory()
    old, pr_id = _persist(factory, commit_sha=OLD)
    with factory() as session:
        SqlAlchemyAnalysisJobQueue(session, worker_id="w1").claim_next()
        session.get(Analysis, old).status = db_enums.AnalysisStatus.RUNNING
        session.commit()
    with factory() as session:
        assert _service(session).cancel_superseded(pull_request_id=pr_id, head_sha=NEW) == [old]
        session.commit()
    assert _state(factory, old) == (
        db_enums.AnalysisStatus.RUNNING,
        db_enums.AnalysisJobStatus.RUNNING,
        f"Cancelled: Superseded by a newer commit of the pull request ({NEW[:12]}).",
    )


# -- worker ----------------------------------------------------------------------------


class FakeOrchestrator:
    """Stands in for the pipeline: writes a result, then lets the head move on."""

    def __init__(self, session, factory, analysis_id, *, at_checkpoint: bool) -> None:
        self.session, self.factory, self.analysis_id = session, factory, analysis_id
        self.at_checkpoint = at_checkpoint
        self.checkpoint = lambda: None

    def execute(self, command) -> None:
        # The API, on a push to the pull request. (Requested first: the in-memory
        # SQLite connection is shared, so a later commit would also commit our writes.)
        with self.factory() as other:
            SqlAlchemyAnalysisJobQueue(other).request_cancel(self.analysis_id, "Superseded.")
            other.commit()
        analysis = self.session.get(Analysis, self.analysis_id)
        analysis.status = db_enums.AnalysisStatus.COMPLETED
        self.session.add(
            ConfidenceReport(
                analysis_id=self.analysis_id,
                confidence_score=90,
                risk_level=db_enums.RiskLevel.LOW,
                summary="stale",
                recommendations=[],
                generated_at=datetime.now(UTC),
            )
        )
        self.session.flush()
        if self.at_checkpoint:
            self.checkpoint()


def _runtime(factory, github, monkeypatch, analysis_id, *, at_checkpoint) -> SqlAlchemyWorkerRuntime:
    monkeypatch.setattr(worker_runner, "ingest_intent_best_effort", lambda **_: None)
    monkeypatch.setattr(
        worker_runner,
        "_create_sql_orchestrator",
        lambda session, settings: FakeOrchestrator(
            session, factory, analysis_id, at_checkpoint=at_checkpoint
        ),
    )
    monkeypatch.setattr(
        worker_runner,
        "load_persisted_analysis_command",
        lambda **_: ExecuteAnalysisCommand(
            analysis_id=analysis_id,
            repository_id=analysis_id,
            repository_path=Path("."),
            base_ref="origin/main",
            head_ref=OLD,
        ),
    )
    return SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=worker_runner.WorkerSettings(
            GITHUB_APP_ID="app-id",
            GITHUB_APP_PRIVATE_KEY="private-key",
            RADIUS_FEATURE_VERDICT_V2="off",
        ),
        github_client=github,
    )


@pytest.mark.parametrize("at_checkpoint", [True, False], ids=["phase_checkpoint", "final_check"])
def test_worker_stops_a_superseded_run_and_never_publishes_its_result(
    monkeypatch, at_checkpoint
) -> None:
    factory = _factory()
    analysis_id, _ = _persist(factory)
    github = FakeGitHubClient()
    runtime = _runtime(factory, github, monkeypatch, analysis_id, at_checkpoint=at_checkpoint)

    assert runtime.run_once() is True

    assert _state(factory, analysis_id) == (
        db_enums.AnalysisStatus.CANCELLED,
        db_enums.AnalysisJobStatus.COMPLETED,
        "Cancelled: Superseded.",
    )
    with factory() as session:  # the run's result was rolled back
        assert session.scalar(select(ConfidenceReport)) is None
    # The in-progress check of the old head is completed as neutral "cancelled".
    (check,) = github.check_runs
    assert check["head_sha"] == OLD
    assert check["status"] == "completed"
    assert check["conclusion"] == "neutral"
    assert check["title"] == "Radius: analysis cancelled"
    assert "Superseded." in check["text"]


def test_worker_skips_a_superseded_retry_and_completes_its_open_check(monkeypatch) -> None:
    factory = _factory()
    analysis_id, _ = _persist(factory)
    with factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session, worker_id="w0")
        queue.claim_next()
        queue.requeue(analysis_id, "boom")  # attempt 1 failed; its check is open
        queue.request_cancel(analysis_id, "Superseded.")
        session.commit()
    github = FakeGitHubClient()
    github.create_check_run(name="Radius confidence", head_sha=OLD, status="in_progress")

    def explode(**_):  # pragma: no cover - must not run
        raise AssertionError("a superseded job must not be cloned")

    runtime = _runtime(factory, github, monkeypatch, analysis_id, at_checkpoint=True)
    monkeypatch.setattr(worker_runner, "load_persisted_analysis_command", explode)

    assert runtime.run_once() is True

    assert _state(factory, analysis_id)[:2] == (
        db_enums.AnalysisStatus.CANCELLED,
        db_enums.AnalysisJobStatus.COMPLETED,
    )
    assert github.check_runs[0]["title"] == "Radius: analysis cancelled"
