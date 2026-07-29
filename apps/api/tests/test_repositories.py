"""Repository API tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def test_repository_endpoints_connect_list_get_and_disconnect() -> None:
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())

    created = client.post(
        "/api/v1/repositories",
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

    assert created.status_code == 201
    body = created.json()
    repository_id = body["data"]["id"]
    assert body["success"] is True
    assert body["data"]["full_name"] == "acme/radius"

    listed = client.get(
        "/api/v1/repositories",
        params={"organizationId": organization_id},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [repository_id]

    fetched = client.get(f"/api/v1/repositories/{repository_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["id"] == repository_id

    disconnected = client.delete(f"/api/v1/repositories/{repository_id}")
    assert disconnected.status_code == 200
    assert disconnected.json()["data"]["status"] == "disconnected"


def test_repository_not_found_uses_error_envelope() -> None:
    client = TestClient(create_app())

    response = client.get(f"/api/v1/repositories/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "NOT_FOUND"
