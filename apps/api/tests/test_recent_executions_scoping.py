"""Recent test executions must be authenticated and tenant-scoped."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def _repository(client: TestClient, org: str) -> str:
    return client.post(
        "/api/v1/repositories",
        headers={"X-Radius-Organization-Id": org},
        json={
            "organizationId": org,
            "repositoryId": 77,
            "name": "shop",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/shop.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]


def test_recent_executions_require_auth_and_repository_scope(monkeypatch) -> None:
    client = TestClient(create_app())
    owner = str(uuid4())
    repo = _repository(client, owner)
    url = f"/api/v1/analyses/{uuid4()}/tests/recent"

    unauthenticated = client.get(url, params={"repositoryId": repo})
    unscoped = client.get(url, headers={"X-Radius-Organization-Id": owner})
    other_tenant = client.get(
        url,
        params={"repositoryId": repo},
        headers={"X-Radius-Organization-Id": str(uuid4())},
    )
    own = client.get(url, params={"repositoryId": repo}, headers={"X-Radius-Organization-Id": owner})

    assert unauthenticated.status_code in (401, 403)
    assert unscoped.status_code == 422
    assert other_tenant.status_code == 403
    assert own.status_code == 200
