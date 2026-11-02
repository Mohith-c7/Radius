"""ONE contract test: the client against the real ASGI app (in-process, no sockets)."""

from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("radius_api", reason="needs the API source tree on PYTHONPATH")
from fastapi.testclient import TestClient  # noqa: E402
from radius_api.config import get_api_settings  # noqa: E402
from radius_api.main import create_app  # noqa: E402
from radius_client import (  # noqa: E402
    ConflictError,
    NotFoundError,
    RadiusClient,
    StaleEtagError,
    TransportResponse,
)


class AsgiTransport:
    """Routes the client's requests into the app through Starlette's TestClient."""

    def __init__(self, http: TestClient) -> None:
        self._http = http

    def request(self, method, url, headers, body, timeout):
        response = self._http.request(method, url, headers=dict(headers), content=body)
        return TransportResponse(
            response.status_code,
            {k.lower(): v for k, v in response.headers.items()},
            response.content,
        )


def test_client_against_real_app(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    get_api_settings.cache_clear()
    http = TestClient(create_app(), base_url="http://radius.test")
    org = str(uuid4())
    seed_headers = {"X-Radius-Organization-Id": org}
    repo = http.post(
        "/api/v1/repositories",
        headers=seed_headers,
        json={
            "organizationId": org,
            "repositoryId": 4242,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    sha = "b" * 40
    analysis_id = http.post(
        "/api/v1/analyses",
        headers=seed_headers,
        json={"repositoryId": repo, "pullRequestId": str(uuid4()), "commitSha": sha},
    ).json()["data"]["id"]
    http.post(
        f"/api/v1/analyses/{analysis_id}/intent/sources",
        headers=seed_headers,
        json={"kind": "pr_body", "text": "## Acceptance Criteria\n- Users must reset password\n"},
    )

    client = RadiusClient(
        "http://radius.test", org, transport=AsgiTransport(http), sleep=lambda _s: None
    )

    # analyses list / get
    listed = client.list_analyses(repository_id=repo, status="pending")
    assert [a["id"] for a in listed] == [analysis_id]
    fetched = client.get_analysis(analysis_id)
    assert fetched["commit_sha"] == sha and fetched["status"] == "pending"

    # confidence: not computed yet -> typed 404 with the server's code
    with pytest.raises(NotFoundError) as missing:
        client.get_confidence(analysis_id)
    assert missing.value.code == "NOT_FOUND"

    # tests upload: analysis is still pending -> typed 409
    with pytest.raises(ConflictError):
        client.upload_test_results(analysis_id, "<testsuite/>", commit_sha=sha)

    # intent read + confirm with ETag, then a stale write
    snapshot = client.get_intent(analysis_id)
    assert snapshot.etag and snapshot.data["criteria"]
    criterion_id = snapshot.data["criteria"][0]["id"]
    confirmed = client.confirm_criterion(analysis_id, criterion_id, if_match=snapshot)
    assert confirmed.data["criterion"]["state"] == "confirmed"
    assert confirmed.etag != snapshot.etag
    with pytest.raises(StaleEtagError):
        client.update_criterion(
            analysis_id, criterion_id, "reopen", if_match=snapshot.if_match()
        )
