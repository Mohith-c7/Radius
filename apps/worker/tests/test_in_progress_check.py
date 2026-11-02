"""The worker opens an in-progress Check Run at job start and completes the same one."""

from __future__ import annotations

from datetime import UTC, datetime
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
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SHA = "c" * 40


class StatefulGitHub:
    def __init__(self) -> None:
        self.check_runs: list[dict] = []
        self.statuses: list[str] = []
        self.comments: list[dict] = []
        self.fail_in_progress_create = False
        self.fail_completed_update = False
        self.fail_comments = False

    def create_installation_token(self, installation_id):
        return type("T", (), {"token": "ghs_x"})()

    def list_check_runs_for_ref(self, *, ref, check_name, **_):
        return [r for r in self.check_runs if r["head_sha"] == ref and r["name"] == check_name]

    def create_check_run(self, **kw):
        if self.fail_in_progress_create and kw["status"] == "in_progress":
            self.fail_in_progress_create = False
            raise RuntimeError("github down")
        run = {**kw, "id": len(self.check_runs) + 1}
        self.check_runs.append(run)
        self.statuses.append(kw["status"])
        return run

    def update_check_run(self, *, check_run_id, **kw):
        if (
            self.fail_completed_update
            and kw["status"] == "completed"
            and kw["conclusion"] != "neutral"
        ):
            self.fail_completed_update = False
            raise RuntimeError("github 502")
        run = next(r for r in self.check_runs if r["id"] == check_run_id)
        run.update(kw)
        self.statuses.append(kw["status"])
        return run

    def list_issue_comments(self, **_):
        return []

    def create_issue_comment(self, **kw):
        if self.fail_comments:
            raise RuntimeError("comment API down")
        self.comments.append(kw)
        return kw


class FakeOrchestrator:
    def execute(self, command):
        return None


class FailingOrchestrator:
    def execute(self, command):
        raise RuntimeError("pipeline exploded")


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


def _runtime(monkeypatch, factory, github, orchestrator=None, **settings):
    monkeypatch.setattr(
        worker_runner, "_create_sql_orchestrator", lambda s, c: orchestrator or FakeOrchestrator()
    )
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


def _job_status(factory, analysis_id):
    with factory() as session:
        return session.scalar(
            select(AnalysisJob.status).where(AnalysisJob.analysis_id == analysis_id)
        )


def test_success_shows_in_progress_then_completes_the_same_check_run(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    analysis_id = _persist(factory)
    assert _runtime(monkeypatch, factory, github).run_once() is True
    assert len(github.check_runs) == 1
    assert github.statuses == ["in_progress", "completed"]
    assert github.check_runs[0]["conclusion"] == "success"
    assert len(github.comments) == 1
    assert _job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED


def test_in_progress_publish_failure_does_not_fail_the_analysis(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    github.fail_in_progress_create = True
    analysis_id = _persist(factory)
    assert _runtime(monkeypatch, factory, github).run_once() is True
    assert _job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED
    assert [r["status"] for r in github.check_runs] == ["completed"]


def test_publish_results_disabled_makes_no_github_calls(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    _persist(factory)
    runtime = _runtime(monkeypatch, factory, github, GITHUB_PUBLISH_RESULTS=False)
    assert runtime.run_once() is True
    assert github.check_runs == []
    assert github.comments == []


def test_final_failure_completes_the_in_progress_run_not_a_second_one(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    analysis_id = _persist(factory)
    runtime = _runtime(
        monkeypatch, factory, github, FailingOrchestrator(), WORKER_JOB_MAX_ATTEMPTS=1
    )
    try:
        runtime.run_once()
    except RuntimeError:
        pass
    assert len(github.check_runs) == 1
    assert github.statuses == ["in_progress", "completed"]
    assert github.check_runs[0]["conclusion"] == "neutral"
    assert _job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.FAILED


def test_result_publish_failure_does_not_leave_the_check_in_progress(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    github.fail_completed_update = True
    analysis_id = _persist(factory)
    assert _runtime(monkeypatch, factory, github).run_once() is True
    assert len(github.check_runs) == 1
    run = github.check_runs[0]
    assert (run["status"], run["conclusion"]) == ("completed", "neutral")
    assert _job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED


def test_comment_failure_keeps_the_completed_check_verdict(monkeypatch) -> None:
    factory, github = _factory(), StatefulGitHub()
    github.fail_comments = True
    _persist(factory)
    assert _runtime(monkeypatch, factory, github).run_once() is True
    run = github.check_runs[0]
    assert (run["status"], run["conclusion"]) == ("completed", "success")
