"""GitHub webhook API tests."""

import hashlib
import hmac
import json
from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def test_pull_request_webhook_creates_analysis_and_replays_delivery() -> None:
    app = create_app()
    organization_id = uuid4()
    app.state.settings.github_default_organization_id = organization_id
    app.state.settings.github_webhook_secret = "secret"
    client = TestClient(app)
    body = _webhook_body()
    headers = _github_headers(body, "delivery-1", "secret")

    first = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/github", content=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert first.json()["data"]["analysisId"] is not None
    assert len(app.state.container.analysis_queue) == 1


def test_github_webhook_rejects_invalid_signature() -> None:
    app = create_app()
    app.state.settings.github_default_organization_id = uuid4()
    app.state.settings.github_webhook_secret = "secret"
    client = TestClient(app)
    body = _webhook_body()
    headers = _github_headers(body, "delivery-2", "wrong-secret")

    response = client.post("/api/v1/webhooks/github", content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


def _webhook_body() -> bytes:
    payload = {
        "action": "synchronize",
        "repository": {
            "id": 404,
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
    return json.dumps(payload, separators=(",", ":")).encode()


def _github_headers(body: bytes, delivery_id: str, secret: str) -> dict[str, str]:
    signature = "sha256=" + hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }
