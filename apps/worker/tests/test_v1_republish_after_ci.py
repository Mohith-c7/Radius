"""The v1 check run and PR comment follow CI results (production ran with v2 off).

Before this, ``POST /tests/results`` re-scored the v1 report in the database
but nothing republished it, so GitHub kept showing "awaiting CI" forever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import radius_worker.runner as worker_runner
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    ConfidenceReport,
    Organization,
    PullRequest,
    Repository,
    TestResultUpload,
)
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_worker.v1_republish import V1CiRepublisher
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

T0 = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _analysis(session: Session, *, pull_request=None, created_at=T0, installation=777):
    if pull_request is None:
        organization = Organization(name="Acme", github_installation_id=installation)
        repository = Repository(
            organization=organization,
            github_repository_id=999,
            name="radius",
            owner="acme",
            default_branch="develop",
            clone_url="https://github.com/acme/radius.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        pull_request = PullRequest(
            repository=repository,
            github_pr_number=158,
            title="Feature",
            source_branch="feature",
            target_branch="develop",
            author="octocat",
            status=db_enums.PullRequestStatus.OPEN,
            opened_at=T0,
        )
        session.add_all([organization, repository, pull_request])
    analysis = Analysis(
        repository=pull_request.repository,
        pull_request=pull_request,
        commit_sha=uuid4().hex + "abcdefgh",
        status=db_enums.AnalysisStatus.COMPLETED,
        started_at=created_at,
        created_at=created_at,
    )
    session.add(analysis)
    session.flush()
    return analysis


def _report(session: Session, analysis, *, at: datetime, status: str = "verified") -> None:
    existing = session.query(ConfidenceReport).filter_by(analysis_id=analysis.id).one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(
        ConfidenceReport(
            analysis_id=analysis.id,
            confidence_score=90 if status == "verified" else 40,
            risk_level=db_enums.RiskLevel.LOW if status == "verified" else db_enums.RiskLevel.CRITICAL,
            verification_status=status,
            summary=f"{status} from CI test results",
            recommendations=[],
            generated_at=at,
        )
    )


def _upload(session: Session, analysis, *, at: datetime) -> None:
    session.add(
        TestResultUpload(
            analysis_id=analysis.id,
            commit_sha=analysis.commit_sha,
            body_sha256=uuid4().hex + uuid4().hex,
            status="passed",
            total_tests=3,
            passed=3,
            failed=0,
            skipped=0,
            duration_ms=5,
            output="",
            created_at=at,
        )
    )


class Recorder:
    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list = []
        self.fail_times = fail_times

    def __call__(self, session: Session, analysis_id) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("GitHub 502")
        self.calls.append(analysis_id)


def _sweeper(factory, publish, **kwargs) -> V1CiRepublisher:
    return V1CiRepublisher(session_factory=factory, publish=publish, **kwargs)


def test_each_new_upload_is_republished_once() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=T0 + timedelta(minutes=1))
        _report(session, analysis, at=T0 + timedelta(minutes=1, seconds=1))
        session.commit()
    publish = Recorder()
    sweeper = _sweeper(factory, publish)

    assert sweeper.tick(now=T0 + timedelta(minutes=2), force=True) == 1
    assert sweeper.tick(now=T0 + timedelta(minutes=3), force=True) == 0

    with factory() as session:
        _upload(session, analysis, at=T0 + timedelta(minutes=4))
        _report(session, analysis, at=T0 + timedelta(minutes=4, seconds=1))
        session.commit()
    assert sweeper.tick(now=T0 + timedelta(minutes=5), force=True) == 1
    assert publish.calls == [analysis.id, analysis.id]


def test_waits_until_the_report_was_rescored() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _report(session, analysis, at=T0)
        _upload(session, analysis, at=T0 + timedelta(minutes=1))
        session.commit()
    publish = Recorder()
    sweeper = _sweeper(factory, publish)

    assert sweeper.tick(now=T0 + timedelta(minutes=2), force=True) == 0
    with factory() as session:
        _report(session, session.get(Analysis, analysis.id), at=T0 + timedelta(minutes=2))
        session.commit()
    assert sweeper.tick(now=T0 + timedelta(minutes=3), force=True) == 1


def test_superseded_analysis_never_overwrites_the_pull_request_comment() -> None:
    factory = _factory()
    with factory() as session:
        old = _analysis(session)
        _analysis(session, pull_request=old.pull_request, created_at=T0 + timedelta(minutes=5))
        _upload(session, old, at=T0 + timedelta(minutes=1))
        _report(session, old, at=T0 + timedelta(minutes=1))
        session.commit()
    publish = Recorder()

    assert _sweeper(factory, publish).tick(now=T0 + timedelta(minutes=6), force=True) == 0
    assert publish.calls == []


def test_v2_on_leaves_republishing_to_the_v2_outbox_and_disabled_does_nothing() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=T0)
        _report(session, analysis, at=T0)
        session.commit()
    publish = Recorder()

    assert _sweeper(factory, publish, verdict_v2_mode=VerdictV2Mode.ON).tick(force=True, now=T0) == 0
    assert _sweeper(factory, publish, enabled=False).tick(force=True, now=T0) == 0
    assert _sweeper(factory, publish, verdict_v2_mode=VerdictV2Mode.SHADOW).tick(
        force=True, now=T0 + timedelta(minutes=1)
    ) == 1


def test_old_uploads_are_outside_the_window() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=T0)
        _report(session, analysis, at=T0)
        session.commit()

    assert _sweeper(factory, Recorder()).tick(now=T0 + timedelta(days=3), force=True) == 0


def test_publish_errors_are_retried_a_bounded_number_of_times() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=T0)
        _report(session, analysis, at=T0)
        session.commit()
    flaky = Recorder(fail_times=1)
    sweeper = _sweeper(factory, flaky)
    assert sweeper.tick(now=T0, force=True) == 0
    assert sweeper.tick(now=T0, force=True) == 1

    broken = Recorder(fail_times=100)
    sweeper = _sweeper(factory, broken, max_attempts=2)
    for _ in range(5):
        sweeper.tick(now=T0, force=True)
    assert broken.fail_times == 98


def test_interval_limits_how_often_the_sweep_runs() -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=T0)
        _report(session, analysis, at=T0)
        session.commit()
    publish = Recorder()
    sweeper = _sweeper(factory, publish, interval_seconds=3600)

    assert sweeper.tick(now=T0) == 1
    with factory() as session:
        _upload(session, analysis, at=T0 + timedelta(minutes=1))
        _report(session, session.get(Analysis, analysis.id), at=T0 + timedelta(minutes=1))
        session.commit()
    assert sweeper.tick(now=T0 + timedelta(minutes=2)) == 0  # not due yet
    assert sweeper.tick(now=T0 + timedelta(minutes=2), force=True) == 1


class PublishingGitHubClient:
    def __init__(self) -> None:
        self.check_runs: list[dict] = []
        self.comments: list[dict] = []

    def create_installation_token(self, installation_id: int):
        return type("Token", (), {"token": "t"})()

    def list_check_runs_for_ref(self, **kwargs):
        return [{"id": 5, "name": kwargs["check_name"]}] if self.check_runs else []

    def create_check_run(self, **kwargs):
        self.check_runs.append(kwargs)
        return {"id": 5}

    def update_check_run(self, **kwargs):
        self.check_runs.append(kwargs)
        return {"id": 5}

    def list_issue_comments(self, **kwargs):
        return []

    def create_issue_comment(self, **kwargs):
        self.comments.append(kwargs)
        return {"id": 6}


def test_worker_runtime_republishes_the_rescored_report_to_github(tmp_path) -> None:
    factory = _factory()
    with factory() as session:
        analysis = _analysis(session)
        _upload(session, analysis, at=datetime.now(UTC) - timedelta(minutes=1))
        _report(session, analysis, at=datetime.now(UTC), status="verified")
        session.commit()
    github = PublishingGitHubClient()
    runtime = worker_runner.SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=tmp_path / "cache",
        git_client=None,  # type: ignore[arg-type]
        settings=worker_runner.WorkerSettings(
            GITHUB_APP_ID="app-id",
            GITHUB_APP_PRIVATE_KEY="private-key",
            DASHBOARD_BASE_URL="https://radius.example",
        ),
        github_client=github,  # type: ignore[arg-type]
    )

    runtime.run_loop(poll_interval_seconds=0, stop_after_idle_cycles=1)

    assert len(github.check_runs) == 1
    assert github.check_runs[0]["conclusion"] in {"success", "neutral"}
    assert "Verified" in github.check_runs[0]["title"]
    assert github.comments[0]["issue_number"] == 158
