"""Webhook tenancy: unknown installations never land in a default organization."""

import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base
from radius_shared.database.models import Organization, Repository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

SECRET = "secret"


def _body(installation_id: int | None = None, repository_id: int = 404) -> bytes:
    payload = {
        "action": "synchronize",
        "repository": {
            "id": repository_id,
            "name": "radius",
            "private": True,
            "default_branch": "main",
            "clone_url": "https://github.com/acme/radius.git",
            "owner": {"login": "acme"},
        },
        "pull_request": {
            "number": 7,
            "title": "Improve parser",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "octocat"},
            "head": {"ref": "feature/parser", "sha": "d" * 40},
            "base": {"ref": "main", "sha": "e" * 40},
            "created_at": "2026-07-29T10:00:00Z",
            "merged_at": None,
        },
    }
    if installation_id is not None:
        payload["installation"] = {"id": installation_id}
    return json.dumps(payload, separators=(",", ":")).encode()


def _headers(body: bytes, delivery_id: str, event: str = "pull_request") -> dict[str, str]:
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }


def _memory_app(*, single_tenant: bool):
    app = create_app()
    app.state.settings.github_default_organization_id = uuid4()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_single_tenant = single_tenant
    return app


def test_unknown_installation_is_rejected_by_default() -> None:
    app = _memory_app(single_tenant=False)
    body = _body(installation_id=999)

    response = TestClient(app).post(
        "/api/v1/webhooks/github", content=body, headers=_headers(body, "d-1")
    )

    assert response.status_code == 403
    assert len(app.state.container.analysis_queue) == 0


def test_single_tenant_mode_falls_back_to_default_organization() -> None:
    app = _memory_app(single_tenant=True)
    body = _body(installation_id=999)

    response = TestClient(app).post(
        "/api/v1/webhooks/github", content=body, headers=_headers(body, "d-2")
    )

    assert response.status_code == 202
    assert response.json()["data"]["analysisId"] is not None


def test_ping_is_acknowledged_without_tenant() -> None:
    app = _memory_app(single_tenant=False)
    body = json.dumps({"zen": "Keep it logically awesome."}).encode()

    response = TestClient(app).post(
        "/api/v1/webhooks/github", content=body, headers=_headers(body, "d-3", "ping")
    )

    assert response.status_code == 202


def test_installation_id_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    org_id = uuid4()
    with Session(engine) as session:
        session.add(Organization(id=org_id, name="Acme", github_installation_id=111))
        session.commit()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("GITHUB_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("GITHUB_DEFAULT_ORGANIZATION_ID", raising=False)
    get_api_settings.cache_clear()
    try:
        client = TestClient(create_app())
        # Installation 111 is linked to Acme, so its repository is filed there.
        first = _body(installation_id=111)
        accepted = client.post(
            "/api/v1/webhooks/github", content=first, headers=_headers(first, "d-4")
        )
        assert accepted.status_code == 202, accepted.text
        # A delivery for the same repository claiming another installation must
        # not re-point Acme at installation 222.
        second = _body(installation_id=222)
        client.post("/api/v1/webhooks/github", content=second, headers=_headers(second, "d-5"))
        # An unknown installation with a new repository is rejected outright.
        third = _body(installation_id=333, repository_id=505)
        rejected = client.post(
            "/api/v1/webhooks/github", content=third, headers=_headers(third, "d-6")
        )
    finally:
        get_api_settings.cache_clear()

    assert rejected.status_code == 403, rejected.text
    with Session(engine) as session:
        assert session.get(Organization, org_id).github_installation_id == 111
        repos = session.query(Repository).all()
        assert [repo.github_repository_id for repo in repos] == [404]
        assert repos[0].organization_id == org_id
