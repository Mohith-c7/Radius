"""A ``synchronize`` push cancels the analysis of the previous head (and only that)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

FIXTURES = (
    Path(__file__).resolve().parents[3] / "packages" / "github" / "tests" / "fixtures" / "webhooks"
)
SECRET = "fixture-webhook-secret"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _post(client: TestClient, event: str, payload: dict, delivery: str) -> dict:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _client(tmp_path, monkeypatch):
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
    return engine, TestClient(create_app())


def _statuses(engine) -> dict[str, tuple[str, str, str | None]]:
    with Session(engine) as session:
        jobs = {j.analysis_id: j for j in session.query(db_models.AnalysisJob)}
        return {
            str(a.id): (a.status.value, jobs[a.id].status.value, jobs[a.id].last_error)
            for a in session.query(db_models.Analysis)
        }


def test_synchronize_cancels_the_previous_head_but_not_manual_analyses(
    tmp_path, monkeypatch
) -> None:
    engine, client = _client(tmp_path, monkeypatch)
    _post(client, "installation", _load("installation_created"), "i-1")
    opened = _post(client, "pull_request", _load("pull_request_opened"), "p-1")
    previous_head = _load("pull_request_synchronize")["before"]
    with Session(engine) as session:  # a manual analysis of the same commit, no PR
        repository = session.query(db_models.Repository).one()
        manual = db_models.Analysis(
            repository_id=repository.id,
            pull_request_id=None,
            commit_sha=previous_head,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add(manual)
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(manual.id)
        session.commit()
        manual_id = str(manual.id)

    pushed = _post(client, "pull_request", _load("pull_request_synchronize"), "p-2")

    assert pushed["cancelledAnalysisIds"] == [opened["analysisId"]]
    states = _statuses(engine)
    assert states[opened["analysisId"]][:2] == ("cancelled", "completed")
    assert states[opened["analysisId"]][2].startswith("Cancelled: Superseded by a newer commit")
    assert states[pushed["analysisId"]][:2] == ("pending", "pending")
    assert states[manual_id] == ("pending", "pending", None)


def test_synchronize_asks_a_running_previous_head_to_stop(tmp_path, monkeypatch) -> None:
    engine, client = _client(tmp_path, monkeypatch)
    _post(client, "installation", _load("installation_created"), "i-1")
    opened = _post(client, "pull_request", _load("pull_request_opened"), "p-1")
    with Session(engine) as session:  # a worker picked it up
        SqlAlchemyAnalysisJobQueue(session, worker_id="w1").claim_next()
        session.query(db_models.Analysis).one().status = db_enums.AnalysisStatus.RUNNING
        session.commit()

    pushed = _post(client, "pull_request", _load("pull_request_synchronize"), "p-2")

    assert pushed["cancelledAnalysisIds"] == [opened["analysisId"]]
    status, job_status, error = _statuses(engine)[opened["analysisId"]]
    # The analysis row belongs to the worker's transaction: only the job is flagged,
    # and the worker stops at its next checkpoint.
    assert (status, job_status) == ("running", "running")
    assert error.startswith("Cancelled: Superseded by a newer commit")
