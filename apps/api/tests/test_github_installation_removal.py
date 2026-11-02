"""Installation / repository removal webhooks: inactive, never hard-deleted."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
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
URL = "/api/v1/webhooks/github"


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


def _install_and_open(client):
    assert post_json(client, "installation", load("installation_created"), "i-1").status_code == 202
    return post_json(client, "pull_request", load("pull_request_opened"), "p-1").json()["data"]


def _row_state(engine):
    with Session(engine) as session:
        repo = session.query(db_models.Repository).one()
        org = session.query(db_models.Organization).first()
        return (
            repo.status.value,
            org.github_installation_status,
            org.github_installation_id,
            {str(a.id): a.status.value for a in session.query(db_models.Analysis)},
            {
                str(j.analysis_id): (j.status.value, j.last_error)
                for j in session.query(db_models.AnalysisJob)
            },
        )


def test_repository_removed_deactivates_repo_and_cancels_queued_work(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        opened = _install_and_open(client)
        removed = post_json(
            client, "installation_repositories", load("installation_repositories_removed"), "r-1"
        )
        assert removed.status_code == 202
        assert removed.json()["data"]["cancelledAnalysisIds"] == [opened["analysisId"]]
        status, _, _, analyses, jobs = _row_state(engine)
        # Inactive, not deleted: the row, PR and analysis history remain.
        assert status == "disconnected"
        assert analyses == {opened["analysisId"]: "cancelled"}
        assert jobs[opened["analysisId"]][0] == "completed"
        assert jobs[opened["analysisId"]][1].startswith("Cancelled:")
        with Session(engine) as session:
            assert session.query(db_models.PullRequest).count() == 1

        # Later deliveries for the removed repo: clear 2xx ignore, nothing queued.
        later = post_json(client, "pull_request", load("pull_request_synchronize"), "p-2")
        assert later.status_code == 202
        data = later.json()["data"]
        assert data["ignored"] is True
        assert data["ignoredReason"] == "repository_disconnected"
        assert data["analysisId"] is None
        push = post_json(client, "push", load("push_feature_branch"), "s-1").json()["data"]
        assert push["ignored"] is True
        assert push["ignoredReason"] == "repository_disconnected"
        assert len(_row_state(engine)[3]) == 1

        # Re-adding the repository reactivates it and analyses work again.
        added = post_json(
            client, "installation_repositories", load("installation_repositories_added"), "r-2"
        )
        assert added.status_code == 202
        assert _row_state(engine)[0] == "connected"
        again = post_json(client, "pull_request", load("pull_request_synchronize"), "p-3").json()[
            "data"
        ]
        assert again["ignored"] is False and again["analysisId"]
    finally:
        get_api_settings.cache_clear()


def test_repository_removal_does_not_cancel_a_running_job(tmp_path: Path, monkeypatch) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        opened = _install_and_open(client)
        with Session(engine) as session:
            job = session.query(db_models.AnalysisJob).one()
            job.status = db_enums.AnalysisJobStatus.RUNNING
            job.attempts = 1
            session.commit()
        removed = post_json(
            client, "installation_repositories", load("installation_repositories_removed"), "r-1"
        ).json()["data"]
    finally:
        get_api_settings.cache_clear()
    assert removed["cancelledAnalysisIds"] == []
    _, _, _, analyses, jobs = _row_state(engine)
    assert analyses[opened["analysisId"]] == "pending"
    assert jobs[opened["analysisId"]][0] == "running"


def test_installation_deleted_marks_everything_inactive_and_reinstall_recovers(
    tmp_path: Path, monkeypatch
) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        opened = _install_and_open(client)
        deleted = post_json(client, "installation", load("installation_deleted"), "d-1")
        assert deleted.status_code == 202
        assert deleted.json()["data"]["cancelledAnalysisIds"] == [opened["analysisId"]]
        status, inst_status, inst_id, analyses, _ = _row_state(engine)
        assert (status, inst_status) == ("disconnected", "deleted")
        assert inst_id == 55001122  # kept, not hard-deleted
        assert analyses == {opened["analysisId"]: "cancelled"}

        ignored = post_json(client, "pull_request", load("pull_request_synchronize"), "p-2").json()[
            "data"
        ]
        assert ignored["ignored"] is True
        assert ignored["ignoredReason"] == "installation_deleted"
        assert ignored["analysisId"] is None

        # Reinstall under a NEW installation id: org active again, id re-pointed.
        reinstall = load("installation_created")
        reinstall["installation"]["id"] = 66002233
        assert post_json(client, "installation", reinstall, "i-2").status_code == 202
        status, inst_status, inst_id, _, _ = _row_state(engine)
        assert (status, inst_status, inst_id) == ("connected", "active", 66002233)
        ok = post_json(client, "pull_request", load("pull_request_synchronize"), "p-3").json()[
            "data"
        ]
        assert ok["ignored"] is False and ok["analysisId"]
    finally:
        get_api_settings.cache_clear()


def test_installation_suspend_pauses_and_unsuspend_resumes(tmp_path: Path, monkeypatch) -> None:
    engine, _, client = _sql_client(tmp_path, monkeypatch)
    try:
        opened = _install_and_open(client)
        suspended = post_json(client, "installation", load("installation_suspend"), "s-1").json()[
            "data"
        ]
        assert suspended["cancelledAnalysisIds"] == [opened["analysisId"]]
        status, inst_status, _, analyses, _ = _row_state(engine)
        assert (status, inst_status) == ("connected", "suspended")
        assert analyses == {opened["analysisId"]: "cancelled"}
        ignored = post_json(client, "pull_request", load("pull_request_synchronize"), "p-2").json()[
            "data"
        ]
        assert ignored["ignored"] is True
        assert ignored["ignoredReason"] == "installation_suspended"

        resumed = post_json(client, "installation", load("installation_unsuspend"), "u-1")
        assert resumed.status_code == 202
        assert _row_state(engine)[1] == "active"
        ok = post_json(client, "pull_request", load("pull_request_synchronize"), "p-3").json()[
            "data"
        ]
        assert ok["ignored"] is False and ok["analysisId"]
    finally:
        get_api_settings.cache_clear()


def test_removal_for_unknown_installation_is_a_clear_2xx_ignore(
    tmp_path: Path, monkeypatch
) -> None:
    _sql_client(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "false")
    get_api_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = post_json(client, "installation", load("installation_deleted"), "d-1")
    finally:
        get_api_settings.cache_clear()
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["ignored"] is True
    assert data["ignoredReason"] == "unknown_installation"


def test_removal_in_one_tenant_never_touches_another_tenants_repository(
    tmp_path: Path, monkeypatch
) -> None:
    engine, org_a, _ = _sql_client(tmp_path, monkeypatch)
    org_b = uuid4()
    with Session(engine) as session:
        session.get(db_models.Organization, org_a).github_installation_id = 55001122
        session.add(db_models.Organization(id=org_b, name="Other", github_installation_id=999))
        session.add(
            db_models.Repository(
                organization_id=org_b,
                github_repository_id=912345678,
                name="radius-sandbox",
                owner="radius-sandbox-owner",
                default_branch="main",
                clone_url="https://github.com/radius-sandbox-owner/radius-sandbox.git",
                visibility=db_enums.RepositoryVisibility.PRIVATE,
                status=db_enums.RepositoryStatus.CONNECTED,
            )
        )
        session.commit()
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "false")
    get_api_settings.cache_clear()
    try:
        client = TestClient(create_app())
        # Org A's installation claims the removal of org B's repository.
        response = post_json(
            client, "installation_repositories", load("installation_repositories_removed"), "r-1"
        )
        assert response.status_code == 202
    finally:
        get_api_settings.cache_clear()
    with Session(engine) as session:
        repo = session.query(db_models.Repository).one()
        assert repo.status == db_enums.RepositoryStatus.CONNECTED


def test_repository_removal_in_memory_mode() -> None:
    app = create_app()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_default_organization_id = uuid4()
    app.state.settings.github_single_tenant = True
    client = TestClient(app)
    opened = _install_and_open(client)
    assert len(app.state.container.analysis_queue) == 1
    removed = post_json(
        client, "installation_repositories", load("installation_repositories_removed"), "r-1"
    ).json()["data"]
    assert removed["cancelledAnalysisIds"] == [opened["analysisId"]]
    assert len(app.state.container.analysis_queue) == 0
    later = post_json(client, "pull_request", load("pull_request_synchronize"), "p-2").json()[
        "data"
    ]
    assert later["ignored"] is True
    assert later["ignoredReason"] == "repository_disconnected"
    assert len(app.state.container.analysis_queue) == 0
