"""F-11: quarantined (flaky) tests endpoint is authenticated and tenant-scoped."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def _repository(client: TestClient, org: str) -> str:
    return client.post(
        "/api/v1/repositories",
        headers={"X-Radius-Organization-Id": org},
        json={
            "organizationId": org,
            "repositoryId": 78,
            "name": "shop",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/shop.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]


def test_flaky_endpoint_requires_auth_and_rejects_unknown_analysis() -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    _repository(client, org)
    url = f"/api/v1/analyses/{uuid4()}/tests/flaky"

    assert client.get(url).status_code in (401, 403, 422)
    missing = client.get(url, headers={"X-Radius-Organization-Id": org})
    assert missing.status_code == 404


def test_flaky_endpoint_validates_parameters() -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    url = f"/api/v1/analyses/{uuid4()}/tests/flaky"
    for params in ({"threshold": 0}, {"threshold": 1.5}, {"window": 1}, {"minComparable": 0}):
        response = client.get(url, params=params, headers={"X-Radius-Organization-Id": org})
        assert response.status_code == 422
