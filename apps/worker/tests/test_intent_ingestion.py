"""IN-02: the worker ingests intent sources for each analysis, best-effort."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import radius_worker.intent_ingestion as intent_module
import radius_worker.runner as worker_runner
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_github.fake_api import (
    RECORDED_HEAD_SHA,
    RECORDED_OWNER,
    RECORDED_REPO,
    FakeGitHub,
    install_recorded_scenario,
)
from radius_intent.application import IntentSnapshotService
from radius_intent.domain import IntentSource, IntentSourceKind
from radius_intent.infrastructure import SqlAlchemyIntentRepository, default_extractors
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

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class TokenOnlyGitHub:
    """The publisher client surface is not used (publishing is off)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.minted = 0
        self.fail = fail

    def create_installation_token(self, installation_id):
        self.minted += 1
        if self.fail:
            raise RuntimeError("cannot mint ghs_secret_token_value")
        return type("T", (), {"token": "installation-token"})()


class FakeOrchestrator:
    def execute(self, command):
        return None


def factory_for_tests() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def persist(factory, *, installation_status="active") -> tuple[UUID, UUID]:
    with factory() as session:
        org = Organization(
            name="Acme",
            github_installation_id=55001122,
            github_installation_status=installation_status,
        )
        repo = Repository(
            organization=org,
            github_repository_id=912345678,
            name=RECORDED_REPO,
            owner=RECORDED_OWNER,
            default_branch="main",
            clone_url="https://github.com/x/y.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        pr = PullRequest(
            repository=repo,
            github_pr_number=1,
            title="Add greeting helper",
            source_branch="feature/greeting",
            target_branch="main",
            author="contributor-test",
            status=db_enums.PullRequestStatus.OPEN,
            opened_at=NOW,
        )
        analysis = Analysis(
            repository=repo,
            pull_request=pr,
            commit_sha=RECORDED_HEAD_SHA,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=NOW,
            created_at=NOW,
        )
        session.add_all([org, repo, pr, analysis])
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id, org.id


def runtime(monkeypatch, factory, github, fake_http, orchestrator=None, **settings):
    monkeypatch.setattr(
        worker_runner, "_create_sql_orchestrator", lambda s, c: orchestrator or FakeOrchestrator()
    )
    monkeypatch.setattr(worker_runner, "load_persisted_analysis_command", lambda **kw: object())
    monkeypatch.setattr(worker_runner, "_github_clone_headers", lambda **kw: ())
    values = {
        "GITHUB_APP_ID": "app-id",
        "GITHUB_APP_PRIVATE_KEY": "key",
        "GITHUB_PUBLISH_RESULTS": False,
        "RADIUS_FEATURE_INTENT_INGESTION": True,  # off by default until F-06
    }
    values.update(settings)
    return SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=worker_runner.WorkerSettings(**values),
        github_client=github,
        intent_transport=fake_http,
    )


def intent_state(factory, org_id, analysis_id):
    with factory() as session:
        repo = SqlAlchemyIntentRepository(session)
        snapshots = IntentSnapshotService(repo, default_extractors())
        return snapshots.history(org_id, str(analysis_id)), repo.get_sources(org_id, str(analysis_id))


def job_status(factory, analysis_id):
    with factory() as session:
        return session.scalar(
            select(AnalysisJob.status).where(AnalysisJob.analysis_id == analysis_id)
        )


def test_each_new_analysis_gets_an_intent_snapshot_automatically(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)

    assert runtime(monkeypatch, factory, github, http).run_once() is True

    history, sources = intent_state(factory, org_id, analysis_id)
    assert [s.version for s in history] == [1]
    assert {s.source_id for s in sources} == {
        "pr-title", "pr-body", "commits", "intent.yml", "issue:12", "issue:13"
    }
    assert history[0].criteria
    assert github.minted == 1  # one token for all of ingestion
    assert len(http.calls) == 5
    assert job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED


def test_rerunning_the_job_is_idempotent(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)
    rt = runtime(monkeypatch, factory, github, http)
    assert rt.run_once() is True
    http.calls.clear()
    # What a retried job (or a re-run of the same analysis) does at its start.
    report = intent_module.ingest_intent_best_effort(
        session_factory=factory,
        analysis_id=analysis_id,
        settings=rt.settings,
        github_client=github,
        installation_id_for=lambda s: 55001122,
        transport=http,
        etag_cache=rt.intent_etag_cache,
    )
    assert report is not None and not report.snapshot_created
    history, _ = intent_state(factory, org_id, analysis_id)
    assert [s.version for s in history] == [1]  # nothing changed, no new version
    assert {c.status for c in http.calls} == {304}  # the runtime-wide ETag cache was used


def test_webhook_recorded_title_and_body_spare_the_pull_request_call(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)
    with factory() as session:
        repo = SqlAlchemyIntentRepository(session)
        IntentSnapshotService(repo, default_extractors()).on_sources_changed(
            str(analysis_id),
            org_id,
            [
                IntentSource.from_text("pr-title", IntentSourceKind.PR_TITLE, "Payload title", NOW),
                IntentSource.from_text("pr-body", IntentSourceKind.PR_BODY, "Payload body. Fixes #12", NOW),
            ],
            NOW,
            trigger="pull_request.opened",
        )
        session.commit()
    assert runtime(monkeypatch, factory, github, http).run_once() is True
    assert not any(p.endswith("/pulls/1") for p in http.paths())
    _, sources = intent_state(factory, org_id, analysis_id)
    texts = {s.source_id: s.text for s in sources}
    assert texts["pr-title"] == "Payload title"
    assert "issue:12" in texts  # link parsed from the payload body
    assert "issue:13" in texts


def test_github_failures_never_fail_the_analysis(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), FakeGitHub()
    http.break_network()
    analysis_id, org_id = persist(factory)
    assert runtime(monkeypatch, factory, github, http).run_once() is True
    assert job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED
    history, _ = intent_state(factory, org_id, analysis_id)
    assert history == ()  # nothing could be fetched, nothing invented


def test_token_failure_is_swallowed_and_secrets_are_not_logged(monkeypatch, caplog) -> None:
    factory, github = factory_for_tests(), TokenOnlyGitHub(fail=True)
    analysis_id, _ = persist(factory)
    with caplog.at_level(logging.INFO):
        assert runtime(monkeypatch, factory, github, FakeGitHub()).run_once() is True
    assert job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED
    assert "ghs_secret_token_value" not in caplog.text


def test_unexpected_ingestion_error_is_logged_and_does_not_fail_the_job(monkeypatch, caplog) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)

    def explode(self, *args, **kwargs):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(intent_module.IntentIngestionService, "apply", explode)
    with caplog.at_level(logging.WARNING):
        assert runtime(monkeypatch, factory, github, http).run_once() is True
    assert "Intent ingestion failed" in caplog.text
    assert job_status(factory, analysis_id) == db_enums.AnalysisJobStatus.COMPLETED
    assert intent_state(factory, org_id, analysis_id)[0] == ()


def test_flag_off_or_no_credentials_means_no_github_calls(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)
    runtime(monkeypatch, factory, github, http, RADIUS_FEATURE_INTENT_INGESTION=False).run_once()
    assert http.calls == [] and github.minted == 0
    assert intent_state(factory, org_id, analysis_id)[0] == ()

    factory2 = factory_for_tests()
    analysis2, org2 = persist(factory2)
    runtime(monkeypatch, factory2, github, http, GITHUB_APP_ID="", GITHUB_APP_PRIVATE_KEY="").run_once()
    assert http.calls == []
    assert intent_state(factory2, org2, analysis2)[0] == ()


def test_inactive_installation_skips_the_job_and_ingestion(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory, installation_status="suspended")
    assert runtime(monkeypatch, factory, github, http).run_once() is True
    assert http.calls == [] and github.minted == 0
    assert intent_state(factory, org_id, analysis_id)[0] == ()


def test_ingestion_function_itself_skips_an_inactive_installation(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, _ = persist(factory, installation_status="deleted")
    settings = worker_runner.WorkerSettings(
        GITHUB_APP_ID="a", GITHUB_APP_PRIVATE_KEY="k", RADIUS_FEATURE_INTENT_INGESTION=True
    )
    assert (
        intent_module.ingest_intent_best_effort(
            session_factory=factory,
            analysis_id=analysis_id,
            settings=settings,
            github_client=github,
            installation_id_for=lambda s: 1,
            transport=http,
        )
        is None
    )
    assert http.calls == []


def test_missing_analysis_or_pr_number_is_skipped(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    settings = worker_runner.WorkerSettings(
        GITHUB_APP_ID="a", GITHUB_APP_PRIVATE_KEY="k", RADIUS_FEATURE_INTENT_INGESTION=True
    )
    kwargs = dict(
        session_factory=factory, settings=settings, github_client=github,
        installation_id_for=lambda s: 1, transport=http,
    )
    assert intent_module.ingest_intent_best_effort(analysis_id=UUID(int=5), **kwargs) is None
    analysis_id, _ = persist(factory)
    with factory() as session:
        session.get(PullRequest, session.get(Analysis, analysis_id).pull_request_id).github_pr_number = 0
        session.commit()
    assert intent_module.ingest_intent_best_effort(analysis_id=analysis_id, **kwargs) is None
    assert http.calls == []


def test_configured_call_budget_is_respected(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)
    runtime(monkeypatch, factory, github, http, RADIUS_INTENT_MAX_API_CALLS=3).run_once()
    assert len(http.calls) == 3
    _, sources = intent_state(factory, org_id, analysis_id)
    assert {"pr-title", "pr-body", "commits", "intent.yml"} == {s.source_id for s in sources}


def test_permission_denied_for_issues_still_builds_the_rest(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    http.deny_prefix(f"/repos/{RECORDED_OWNER}/{RECORDED_REPO}/issues")
    analysis_id, org_id = persist(factory)
    runtime(monkeypatch, factory, github, http).run_once()
    history, sources = intent_state(factory, org_id, analysis_id)
    assert history and not any(s.source_id.startswith("issue:") for s in sources)


def test_issue_comments_setting_adds_comment_sources(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, org_id = persist(factory)
    runtime(monkeypatch, factory, github, http, RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS=True).run_once()
    _, sources = intent_state(factory, org_id, analysis_id)
    assert "issue-comments:12" in {s.source_id for s in sources}


def test_ingestion_is_off_by_default_and_cross_repo_setting_defaults_off() -> None:
    settings = worker_runner.WorkerSettings(GITHUB_APP_ID="a", GITHUB_APP_PRIVATE_KEY="k")
    assert settings.intent_ingestion_enabled is False
    assert settings.intent_allow_cross_repo is False
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    analysis_id, _ = persist(factory)
    assert (
        intent_module.ingest_intent_best_effort(
            session_factory=factory, analysis_id=analysis_id, settings=settings,
            github_client=github, installation_id_for=lambda s: 1, transport=http,
        )
        is None
    )
    assert http.calls == []


def test_cross_repo_setting_reaches_the_collector(monkeypatch) -> None:
    factory, github, http = factory_for_tests(), TokenOnlyGitHub(), install_recorded_scenario(FakeGitHub())
    base = f"/repos/{RECORDED_OWNER}/{RECORDED_REPO}"
    http.put_pull(RECORDED_OWNER, RECORDED_REPO, 1, title="t", body="Fixes other/lib#7", head_sha=RECORDED_HEAD_SHA)
    http.put_issue("other", "lib", 7, title="Other", body="other repo text")
    analysis_id, org_id = persist(factory)
    runtime(monkeypatch, factory, github, http).run_once()
    assert not any(p.startswith("/repos/other/") for p in http.paths())
    assert base
    factory2 = factory_for_tests()
    analysis2, org2 = persist(factory2)
    runtime(monkeypatch, factory2, github, http, RADIUS_INTENT_ALLOW_CROSS_REPO=True).run_once()
    _, sources = intent_state(factory2, org2, analysis2)
    assert "issue:other:lib:7" in {s.source_id for s in sources}
