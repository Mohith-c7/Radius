"""Analysis API tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


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
    pull_request_id = str(uuid4())

    started = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": repository_id,
            "pullRequestId": pull_request_id,
            "commitSha": "a" * 40,
        },
    )

    assert started.status_code == 202
    body = started.json()
    analysis_id = body["data"]["id"]
    assert body["data"]["status"] == "pending"
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
        "pullRequestId": str(uuid4()),
        "commitSha": "b" * 40,
    }

    first = client.post("/api/v1/analyses", headers=headers, json=payload)
    second = client.post("/api/v1/analyses", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert len(app.state.container.analysis_queue) == 1
