"""Analysis API tests."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base
from radius_shared.database.models import Organization
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def test_analysis_endpoints_start_list_get_and_rerun() -> None:
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": organization_id}
    repository = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": organization_id,
            "repositoryId": 101,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    )
    repository_id = repository.json()["data"]["id"]
    started = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": repository_id,
            "commitSha": "a" * 40,
        },
    )

    assert started.status_code == 202
    body = started.json()
    analysis_id = body["data"]["id"]
    assert body["data"]["status"] == "pending"
    assert body["data"]["pull_request_id"] is None
    assert len(app.state.container.analysis_queue) == 1

    listed = client.get(
        "/api/v1/analyses",
        headers=headers,
        params={"repositoryId": repository_id, "status": "pending"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [analysis_id]

    fetched = client.get(f"/api/v1/analyses/{analysis_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["changed_files"] == []

    rerun = client.post(f"/api/v1/analyses/{analysis_id}/rerun", headers=headers)
    assert rerun.status_code == 202
    assert rerun.json()["data"]["id"] != analysis_id


def test_missing_blast_radius_returns_not_found_envelope() -> None:
    client = TestClient(create_app())
    headers = {"X-Radius-Organization-Id": str(uuid4())}

    response = client.get(
        f"/api/v1/analyses/{uuid4()}/blast-radius",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["success"] is False


def test_start_analysis_replays_idempotent_response() -> None:
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())
    headers = {
        "X-Radius-Organization-Id": organization_id,
        "Idempotency-Key": "start-analysis",
    }
    repository = client.post(
        "/api/v1/repositories",
        headers={"X-Radius-Organization-Id": organization_id},
        json={
            "organizationId": organization_id,
            "repositoryId": 202,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    )
    payload = {
        "repositoryId": repository.json()["data"]["id"],
        "commitSha": "b" * 40,
    }

    first = client.post("/api/v1/analyses", headers=headers, json=payload)
    second = client.post("/api/v1/analyses", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert len(app.state.container.analysis_queue) == 1


@pytest.fixture
def sql_client(tmp_path, monkeypatch):
    """The SQL backend with foreign keys enforced, as on PostgreSQL."""

    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    def _enforce_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(Engine, "connect", _enforce_foreign_keys)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    get_api_settings.cache_clear()
    organization_id = uuid4()
    with Session(engine) as session:
        session.add(Organization(id=organization_id, name="Acme"))
        session.commit()
    client = TestClient(create_app(), raise_server_exceptions=False)
    headers = {"X-Radius-Organization-Id": str(organization_id)}
    repository = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": str(organization_id),
            "repositoryId": 303,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    )
    assert repository.status_code == 201, repository.text
    yield client, headers, repository.json()["data"]["id"]
    event.remove(Engine, "connect", _enforce_foreign_keys)
    get_api_settings.cache_clear()
    engine.dispose()


def test_manual_branch_analysis_without_pull_request_is_stored_and_listed(sql_client) -> None:
    client, headers, repository_id = sql_client

    started = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repository_id, "pullRequestId": None, "commitSha": "c" * 40},
    )

    assert started.status_code == 202, started.text
    analysis = started.json()["data"]
    assert analysis["pull_request_id"] is None
    listed = client.get("/api/v1/analyses", headers=headers, params={"repositoryId": repository_id})
    assert listed.status_code == 200
    assert [(a["id"], a["pull_request_id"]) for a in listed.json()["data"]] == [
        (analysis["id"], None)
    ]
    fetched = client.get(f"/api/v1/analyses/{analysis['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["pull_request_id"] is None


def test_unknown_pull_request_id_is_a_json_not_found_not_a_plain_500(sql_client) -> None:
    client, headers, repository_id = sql_client

    response = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repository_id, "pullRequestId": str(uuid4()), "commitSha": "d" * 40},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PULL_REQUEST_NOT_FOUND"
