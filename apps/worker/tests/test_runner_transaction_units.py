"""C-04: the runner works in bounded units; no transaction is open during git or GitHub calls.

SQLite-compatible: every session the runtime opens is tracked, and each fake external call
records which tracked sessions are inside a transaction at that moment.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
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

SHA = "e" * 40


class TrackingFactory:
    """A session factory that remembers every session it handed out."""

    def __init__(self, tmp_path: Path) -> None:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'units.db'}")
        Base.metadata.create_all(engine)
        self._factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.sessions: list[Session] = []

    def __call__(self) -> Session:
        session = self._factory()
        self.sessions.append(session)
        return session

    def open_transactions(self) -> int:
        return sum(1 for s in self.sessions if s.in_transaction())


def _persist(factory: TrackingFactory) -> object:
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


class Probe:
    """Records transactions at every external call (git, GitHub, ingestion)."""

    def __init__(self, factory: TrackingFactory) -> None:
        self.factory = factory
        self.calls: list[tuple[str, int]] = []

    def note(self, label: str) -> None:
        self.calls.append((label, self.factory.open_transactions()))

    def during(self, label: str) -> list[int]:
        return [open_ for name, open_ in self.calls if name == label]


class FakeGit:
    def __init__(self, probe: Probe, *, fail_clone: bool = False) -> None:
        self.probe = probe
        self.fail_clone = fail_clone

    def clone_or_fetch(self, clone_url, destination, *, extra_headers=()):
        self.probe.note("git:clone_or_fetch")
        if self.fail_clone:
            raise RuntimeError("network down during clone")
        return Path("repo")

    def fetch_pull_request(self, repository_path, number, *, extra_headers=()):
        self.probe.note("git:fetch_pull_request")

    @contextlib.contextmanager
    def analysis_worktree(self, repository_path, commit_sha, root, analysis_id):
        self.probe.note("git:analysis_worktree")
        yield Path("worktree")
        self.probe.note("git:worktree_removed")

    def checkout(self, repository_path, ref):  # pragma: no cover - worktree path is used
        self.probe.note("git:checkout")


class FakeGitHub:
    def __init__(self, probe: Probe) -> None:
        self.probe = probe
        self.check_runs: list[dict] = []

    def create_installation_token(self, installation_id):
        self.probe.note("github:token")
        return type("T", (), {"token": "ghs_x"})()

    def list_check_runs_for_ref(self, *, ref, check_name, **_):
        return [r for r in self.check_runs if r["head_sha"] == ref and r["name"] == check_name]

    def create_check_run(self, **kw):
        self.probe.note(f"github:create:{kw['status']}")
        run = {**kw, "id": len(self.check_runs) + 1}
        self.check_runs.append(run)
        return run

    def update_check_run(self, *, check_run_id, **kw):
        self.probe.note(f"github:update:{kw['status']}")
        run = next(r for r in self.check_runs if r["id"] == check_run_id)
        run.update(kw)
        return run

    def list_issue_comments(self, **_):
        return []

    def create_issue_comment(self, **kw):
        self.probe.note("github:comment")
        return kw


class Pipeline:
    """Orchestrator stand-in: records and optionally writes through the job session."""

    def __init__(self, probe: Probe, session_holder: dict, *, write=None, fail=False) -> None:
        self.probe = probe
        self.holder = session_holder
        self.write = write
        self.fail = fail
        self.session_in_transaction_during_pipeline: bool | None = None

    def execute(self, command):
        session = self.holder["session"]
        if self.write is not None:
            self.write(session)
            session.flush()
        self.session_in_transaction_during_pipeline = session.in_transaction()
        self.probe.note("pipeline")
        if self.fail:
            raise RuntimeError("pipeline blew up")


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


def _runtime(monkeypatch, factory, probe, *, fail_clone=False, pipeline_kwargs=None, **settings):
    holder: dict = {}
    pipeline = Pipeline(probe, holder, **(pipeline_kwargs or {}))

    def make_orchestrator(session, _settings):
        holder["session"] = session
        return pipeline

    monkeypatch.setattr(worker_runner, "_create_sql_orchestrator", make_orchestrator)
    monkeypatch.setattr(
        worker_runner, "_github_report", lambda session, aid, s: _report(aid)
    )
    monkeypatch.setattr(
        worker_runner,
        "ingest_intent_best_effort",
        lambda **kw: probe.note("ingest_intent"),
    )
    github = FakeGitHub(probe)
    runtime = SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=FakeGit(probe, fail_clone=fail_clone),
        settings=worker_runner.WorkerSettings(
            GITHUB_APP_ID="app-id",
            GITHUB_APP_PRIVATE_KEY="key",
            WORKER_JOB_RETRY_BASE_SECONDS=0,
            **settings,
        ),
        github_client=github,
    )
    return runtime, pipeline, github


def _state(factory, analysis_id):
    with factory() as session:
        analysis = session.get(Analysis, analysis_id)
        job = session.scalar(select(AnalysisJob).where(AnalysisJob.analysis_id == analysis_id))
        return analysis.status, job.status, job.last_error


def test_no_transaction_is_open_during_git_or_github_calls(monkeypatch, tmp_path) -> None:
    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    probe = Probe(factory)
    runtime, pipeline, github = _runtime(monkeypatch, factory, probe)
    probe.calls.clear()  # ignore the setup sessions

    assert runtime.run_once() is True

    labels = {label for label, _ in probe.calls}
    assert {
        "github:create:in_progress",
        "github:token",
        "ingest_intent",
        "git:clone_or_fetch",
        "git:fetch_pull_request",
        "git:analysis_worktree",
        "pipeline",
        "github:update:completed",
    } <= labels, probe.calls
    for label, open_transactions in probe.calls:
        if label == "pipeline":
            continue  # the analysis pipeline is the one remaining single-transaction unit
        assert open_transactions == 0, (label, probe.calls)
    # the result is published only once the job is committed, and nothing is left open
    assert factory.open_transactions() == 0
    status, job_status, _ = _state(factory, analysis_id)
    assert job_status == db_enums.AnalysisJobStatus.COMPLETED
    assert status in {db_enums.AnalysisStatus.RUNNING, db_enums.AnalysisStatus.COMPLETED}


def test_the_order_of_units_is_running_then_read_then_git_then_pipeline_then_publish(
    monkeypatch, tmp_path
) -> None:
    factory = TrackingFactory(tmp_path)
    _persist(factory)
    probe = Probe(factory)
    runtime, _, _ = _runtime(monkeypatch, factory, probe)
    probe.calls.clear()

    runtime.run_once()

    order = [label for label, _ in probe.calls]
    assert order.index("github:create:in_progress") < order.index("git:clone_or_fetch")
    assert order.index("github:token") < order.index("git:clone_or_fetch")
    assert order.index("git:analysis_worktree") < order.index("pipeline")
    assert order.index("pipeline") < order.index("github:update:completed")


def test_pipeline_writes_and_job_completion_commit_together(monkeypatch, tmp_path) -> None:
    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    probe = Probe(factory)

    def write(session):
        session.get(Analysis, analysis_id).commit_sha = "f" * 40

    runtime, pipeline, _ = _runtime(
        monkeypatch, factory, probe, pipeline_kwargs={"write": write}
    )

    runtime.run_once()

    assert pipeline.session_in_transaction_during_pipeline is True
    with factory() as session:
        assert session.get(Analysis, analysis_id).commit_sha == "f" * 40
    assert _state(factory, analysis_id)[1] == db_enums.AnalysisJobStatus.COMPLETED


def test_a_failing_pipeline_rolls_back_its_writes_and_leaves_a_consistent_state(
    monkeypatch, tmp_path
) -> None:
    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    probe = Probe(factory)

    def write(session):
        session.get(Analysis, analysis_id).commit_sha = "f" * 40

    runtime, _, github = _runtime(
        monkeypatch, factory, probe, pipeline_kwargs={"write": write, "fail": True}
    )

    with pytest.raises(RuntimeError, match="pipeline blew up"):
        runtime.run_once()

    with factory() as session:
        assert session.get(Analysis, analysis_id).commit_sha == SHA  # the partial write is gone
    status, job_status, error = _state(factory, analysis_id)
    # attempt 1 of 3: back in the queue and visibly pending again, with the reason recorded
    assert job_status == db_enums.AnalysisJobStatus.PENDING
    assert status == db_enums.AnalysisStatus.PENDING
    assert "pipeline blew up" in error
    assert factory.open_transactions() == 0
    # nothing was published as a result
    assert not any(run["status"] == "completed" for run in github.check_runs)


def test_a_git_failure_on_the_last_attempt_fails_analysis_and_job_and_closes_the_check(
    monkeypatch, tmp_path
) -> None:
    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    probe = Probe(factory)
    runtime, _, github = _runtime(
        monkeypatch, factory, probe, fail_clone=True, WORKER_JOB_MAX_ATTEMPTS=1
    )
    probe.calls.clear()

    with pytest.raises(RuntimeError, match="network down"):
        runtime.run_once()

    status, job_status, _ = _state(factory, analysis_id)
    assert status == db_enums.AnalysisStatus.FAILED
    assert job_status == db_enums.AnalysisJobStatus.FAILED
    assert factory.open_transactions() == 0
    # even the failure publication happens with no transaction open
    for label, open_transactions in probe.calls:
        assert open_transactions == 0, (label, probe.calls)
    assert github.check_runs and github.check_runs[-1]["status"] == "completed"
    assert github.check_runs[-1]["conclusion"] == "neutral"


def test_a_cancelled_analysis_is_skipped_before_any_git_or_github_work(
    monkeypatch, tmp_path
) -> None:
    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    with factory() as session:
        session.get(Analysis, analysis_id).status = db_enums.AnalysisStatus.CANCELLED
        session.commit()
    probe = Probe(factory)
    runtime, _, github = _runtime(monkeypatch, factory, probe)
    probe.calls.clear()

    assert runtime.run_once() is True

    assert probe.calls == []
    assert github.check_runs == []
    assert factory.open_transactions() == 0
    assert _state(factory, analysis_id)[1] != db_enums.AnalysisJobStatus.PENDING


def test_read_only_units_refuse_pending_changes(tmp_path) -> None:
    """The helper that ends a read transaction never silently commits somebody's writes."""

    factory = TrackingFactory(tmp_path)
    analysis_id = _persist(factory)
    with factory() as session:
        session.get(Analysis, analysis_id).commit_sha = "a" * 40
        with pytest.raises(RuntimeError, match="read-only"):
            worker_runner._end_read_transaction(session)
        session.rollback()
        session.get(Analysis, analysis_id)
        worker_runner._end_read_transaction(session)
        assert not session.in_transaction()
