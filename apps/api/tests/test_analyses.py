"""Analysis API tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def test_analysis_endpoints_start_list_get_and_rerun() -> None:
    app = create_app()
    client = TestClient(app)
    repository_id = str(uuid4())
    pull_request_id = str(uuid4())

    started = client.post(
        "/api/v1/analyses",
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
        params={"repositoryId": repository_id, "status": "pending"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [analysis_id]

    fetched = client.get(f"/api/v1/analyses/{analysis_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["changed_files"] == []

    rerun = client.post(f"/api/v1/analyses/{analysis_id}/rerun")
    assert rerun.status_code == 202
    assert rerun.json()["data"]["id"] != analysis_id


def test_missing_blast_radius_returns_not_found_envelope() -> None:
    client = TestClient(create_app())

    response = client.get(f"/api/v1/analyses/{uuid4()}/blast-radius")

    assert response.status_code == 404
    assert response.json()["success"] is False
