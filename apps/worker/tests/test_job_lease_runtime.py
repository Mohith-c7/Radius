"""Worker runtime: lease heartbeat/ownership (C-02), early running + publish-after-commit (C-04)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import radius_worker.runner as worker_runner
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_github.publisher import GitHubAnalysisReport
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.healthcheck import file_is_fresh
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

SHA = "d" * 40


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    # A file database: two sessions really are two connections, so "committed"
    # is observable from a second session.
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist(factory) -> object:
    with factory() as session:
        org = Organization(name="Acme", github_installation_id=777)
        repo = Repository(
            organization=org,
            github_repository_id=4242,
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
            commit_sha=SHA,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([org, repo, pr, analysis])
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id


def _report(analysis_id) -> GitHubAnalysisReport:
    return GitHubAnalysisReport(
        analysis_id=analysis_id,
        owner="acme",
        repository_name="radius",
        pull_request_number=7,
        head_sha=SHA,
        confidence_score=80,
        risk_level="low",
        summary="ok",
        recommendations=(),
        verification_status="verified",
    )


class RecordingGitHub:
    """Records what a second session sees at every GitHub call."""

    def __init__(self, factory) -> None:
        self.factory = factory
        self.check_runs: list[dict] = []
        self.observed: list[tuple[str, str]] = []

    def _observe(self, label: str) -> None:
        with self.factory() as session:
            job = session.scalar(select(AnalysisJob))
            self.observed.append((label, job.status.value))

    def create_installation_token(self, installation_id):
        return type("T", (), {"token": "ghs_x"})()

    def list_check_runs_for_ref(self, *, ref, check_name, **_):
        return [r for r in self.check_runs if r["head_sha"] == ref and r["name"] == check_name]

    def create_check_run(self, **kw):
        self._observe(f"create:{kw['status']}")
        run = {**kw, "id": len(self.check_runs) + 1}
        self.check_runs.append(run)
        return run

    def update_check_run(self, *, check_run_id, **kw):
        self._observe(f"update:{kw['status']}")
        run = next(r for r in self.check_runs if r["id"] == check_run_id)
        run.update(kw)
        return run

    def list_issue_comments(self, **_):
        return []

    def create_issue_comment(self, **kw):
        self._observe("comment")
        return kw


def _runtime(monkeypatch, factory, github, orchestrator, **settings):
    monkeypatch.setattr(worker_runner, "_create_sql_orchestrator", lambda s, c: orchestrator)
    monkeypatch.setattr(worker_runner, "load_persisted_analysis_command", lambda **kw: object())
    monkeypatch.setattr(worker_runner, "_github_clone_headers", lambda **kw: ())
    monkeypatch.setattr(worker_runner, "_github_report", lambda session, aid, s: _report(aid))
    return SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=worker_runner.WorkerSettings(
            GITHUB_APP_ID="app-id", GITHUB_APP_PRIVATE_KEY="key", **settings
        ),
        github_client=github,
    )


class Probe:
    """Orchestrator stand-in running a callback from the pipeline."""

    def __init__(self, callback) -> None:
        self.callback = callback

    def execute(self, command):
        self.callback()


def _job_row(factory):
    with factory() as session:
        return session.scalar(select(AnalysisJob))


def test_running_is_visible_during_the_pipeline_and_result_is_published_after_commit(
    monkeypatch, tmp_path
) -> None:
    factory = _factory(tmp_path)
    analysis_id = _persist(factory)
    github = RecordingGitHub(factory)
    seen: list[str] = []

    def during_pipeline() -> None:
        with factory() as other:
            seen.append(other.get(Analysis, analysis_id).status.value)

    runtime = _runtime(monkeypatch, factory, github, Probe(during_pipeline))
    assert runtime.run_once() is True

    assert seen == ["running"]  # committed before the long pipeline, not at its end
    final_calls = [obs for obs in github.observed if obs[0] != "create:in_progress"]
    assert final_calls, "a result must be published"
    # Every publication of the result happened after the job was committed completed.
    assert all(state == "completed" for _label, state in final_calls), github.observed
    assert _job_row(factory).status == db_enums.AnalysisJobStatus.COMPLETED


def test_publish_does_not_happen_when_the_completion_commit_cannot_be_made(
    monkeypatch, tmp_path
) -> None:
    factory = _factory(tmp_path)
    _persist(factory)
    github = RecordingGitHub(factory)
    runtime = _runtime(monkeypatch, factory, github, Probe(lambda: None), WORKER_JOB_RETRY_BASE_SECONDS=0)

    original = SqlAlchemyAnalysisJobQueue.complete

    def complete_then_break(self, analysis_id):
        original(self, analysis_id)
        raise RuntimeError("database went away at commit time")

    monkeypatch.setattr(SqlAlchemyAnalysisJobQueue, "complete", complete_then_break)
    try:
        runtime.run_once()
    except RuntimeError:
        pass
    assert [label for label, _ in github.observed] == ["create:in_progress"]
    assert _job_row(factory).status == db_enums.AnalysisJobStatus.PENDING  # retried later


def test_worker_that_lost_its_lease_publishes_nothing_and_does_not_touch_the_new_owner(
    monkeypatch, tmp_path
) -> None:
    factory = _factory(tmp_path)
    analysis_id = _persist(factory)
    github = RecordingGitHub(factory)

    def steal_the_job() -> None:
        # While this worker is "slow", its lease expires and worker B claims the job.
        with factory() as session:
            row = session.scalar(select(AnalysisJob))
            row.locked_at = datetime.now(UTC) - timedelta(hours=1)
            session.commit()
        with factory() as session:
            other = SqlAlchemyAnalysisJobQueue(
                session, stale_after=timedelta(minutes=30), max_attempts=3, worker_id="worker-b"
            )
            assert other.claim_next() is not None
            session.commit()

    runtime = _runtime(monkeypatch, factory, github, Probe(steal_the_job))
    assert runtime.run_once() is True  # abandoning a lost job is not an error

    row = _job_row(factory)
    assert row.status == db_enums.AnalysisJobStatus.RUNNING
    assert row.claimed_by == "worker-b"
    assert row.attempts == 2
    assert [label for label, _ in github.observed] == ["create:in_progress"]  # no result published
    with factory() as session:
        assert session.get(Analysis, analysis_id).status != db_enums.AnalysisStatus.COMPLETED


def test_heartbeat_renews_the_lease_while_a_long_job_runs(monkeypatch, tmp_path) -> None:
    factory = _factory(tmp_path)
    _persist(factory)
    github = RecordingGitHub(factory)
    health = tmp_path / "health"
    observed: list[datetime] = []

    def slow_pipeline() -> None:
        first = _job_row(factory).locked_at
        time.sleep(2.6)
        observed.extend([first, _job_row(factory).locked_at])

    runtime = _runtime(
        monkeypatch,
        factory,
        github,
        Probe(slow_pipeline),
        WORKER_HEARTBEAT_INTERVAL_SECONDS=1,
        WORKER_HEALTH_FILE=str(health),
    )
    assert runtime.run_once() is True
    first, later = observed
    assert later > first  # locked_at was renewed during the run
    assert file_is_fresh(str(health), 60)


def test_file_is_fresh_reports_missing_and_old_files(tmp_path) -> None:
    missing = tmp_path / "nope"
    assert file_is_fresh(str(missing), 60) is False
    path = tmp_path / "h"
    path.write_text("")
    assert file_is_fresh(str(path), 60) is True
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert file_is_fresh(str(path), 60) is False
    assert file_is_fresh(str(path), 7200) is True
