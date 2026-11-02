"""Regression tests for GitHub integration defects found in F-06 validation."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

FIXTURES = (
    Path(__file__).resolve().parents[3] / "packages" / "github" / "tests" / "fixtures" / "webhooks"
)
SECRET = "fixture-webhook-secret"
URL = "/api/v1/webhooks/github"


def _sql_client(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    org_id = uuid4()
    with Session(engine) as session:
        session.add(db_models.Organization(id=org_id, name="Sandbox"))
        session.commit()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "true")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(org_id))
    get_api_settings.cache_clear()
    return engine, org_id, TestClient(create_app())


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def post_json(client: TestClient, event: str, payload: dict, delivery: str):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )


def repo_row(engine) -> db_models.Repository:
    with Session(engine) as session:
        row = session.query(db_models.Repository).one()
        session.expunge(row)
        return row


# --- Defect 1: default branch -------------------------------------------------


def test_installation_sync_uses_default_branch_when_payload_has_it(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        payload = load("installation_created")
        payload["repositories"][0]["default_branch"] = "trunk"
        assert post_json(client, "installation", payload, "i-1").status_code == 202
    finally:
        get_api_settings.cache_clear()
    assert repo_row(engine).default_branch == "trunk"


def test_pull_request_delivery_corrects_provisional_default_branch(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        assert post_json(client, "installation", load("installation_created"), "i-1").status_code == 202
        # Installation payloads carry no default branch: provisional value.
        assert repo_row(engine).default_branch == "main"
        pr = load("pull_request_opened")
        pr["repository"]["default_branch"] = "develop"
        assert post_json(client, "pull_request", pr, "p-1").status_code == 202
    finally:
        get_api_settings.cache_clear()
    assert repo_row(engine).default_branch == "develop"


def test_default_branch_rename_is_applied_by_push(tmp_path: Path, monkeypatch) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        push = load("push_feature_branch")
        push["repository"]["default_branch"] = "main"
        post_json(client, "push", push, "s-1")
        assert repo_row(engine).default_branch == "main"
        renamed = copy.deepcopy(push)
        renamed["repository"]["default_branch"] = "release"
        post_json(client, "push", renamed, "s-2")
    finally:
        get_api_settings.cache_clear()
    assert repo_row(engine).default_branch == "release"


def test_pull_request_falls_back_to_base_repo_default_branch(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        pr = load("pull_request_opened")
        del pr["repository"]["default_branch"]
        pr["pull_request"]["base"]["repo"]["default_branch"] = "integration"
        assert post_json(client, "pull_request", pr, "p-1").status_code == 202
    finally:
        get_api_settings.cache_clear()
    assert repo_row(engine).default_branch == "integration"


def test_missing_default_branch_everywhere_keeps_existing_value(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        first = load("pull_request_opened")
        first["repository"]["default_branch"] = "develop"
        post_json(client, "pull_request", first, "p-1")
        second = load("pull_request_synchronize")
        del second["repository"]["default_branch"]
        del second["pull_request"]["base"]["repo"]["default_branch"]
        assert post_json(client, "pull_request", second, "p-2").status_code == 202
    finally:
        get_api_settings.cache_clear()
    assert repo_row(engine).default_branch == "develop"




# --- Defect 5: closing a PR cancels queued-not-started analyses ---------------


def test_closing_a_pull_request_cancels_queued_analyses_in_memory() -> None:
    from uuid import uuid4 as _uuid4

    app = create_app()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_default_organization_id = _uuid4()
    app.state.settings.github_single_tenant = True
    client = TestClient(app)
    opened = post_json(client, "pull_request", load("pull_request_opened"), "o").json()["data"]
    closed = post_json(client, "pull_request", load("pull_request_closed"), "c").json()["data"]
    assert closed["cancelledAnalysisIds"] == [opened["analysisId"]]
    assert len(app.state.container.analysis_queue) == 0


def test_closing_cancels_pending_job_and_analysis_but_not_a_running_one(
    tmp_path: Path, monkeypatch
) -> None:
    from radius_shared.database import enums as db_enums

    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        first = post_json(client, "pull_request", load("pull_request_opened"), "p1").json()["data"]
        second = post_json(client, "pull_request", load("pull_request_synchronize"), "p2").json()[
            "data"
        ]
        # A worker has claimed the first job and is running it.
        with Session(engine) as session:
            job = (
                session.query(db_models.AnalysisJob)
                .filter_by(analysis_id=UUID(first["analysisId"]))
                .one()
            )
            job.status = db_enums.AnalysisJobStatus.RUNNING
            job.attempts = 1
            session.commit()
        closed = post_json(client, "pull_request", load("pull_request_closed"), "p3").json()["data"]
    finally:
        get_api_settings.cache_clear()
    assert closed["cancelledAnalysisIds"] == [second["analysisId"]]
    with Session(engine) as session:
        running = session.get(db_models.Analysis, UUID(first["analysisId"]))
        cancelled = session.get(db_models.Analysis, UUID(second["analysisId"]))
        assert running.status == db_enums.AnalysisStatus.PENDING
        assert cancelled.status == db_enums.AnalysisStatus.CANCELLED
        jobs = {str(j.analysis_id): j for j in session.query(db_models.AnalysisJob)}
        assert jobs[first["analysisId"]].status == db_enums.AnalysisJobStatus.RUNNING
        done = jobs[second["analysisId"]]
        assert done.status == db_enums.AnalysisJobStatus.COMPLETED
        assert done.last_error.startswith("Cancelled:")


def test_closing_leaves_retry_pending_job_alone(tmp_path: Path, monkeypatch) -> None:
    from radius_shared.database import enums as db_enums

    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        opened = post_json(client, "pull_request", load("pull_request_opened"), "p1").json()["data"]
        with Session(engine) as session:
            job = session.query(db_models.AnalysisJob).one()
            job.attempts = 1  # failed once, requeued; in-progress check is on GitHub
            session.commit()
        closed = post_json(client, "pull_request", load("pull_request_closed"), "p2").json()["data"]
    finally:
        get_api_settings.cache_clear()
    assert closed["cancelledAnalysisIds"] == []
    with Session(engine) as session:
        analysis = session.get(db_models.Analysis, UUID(opened["analysisId"]))
        assert analysis.status == db_enums.AnalysisStatus.PENDING
