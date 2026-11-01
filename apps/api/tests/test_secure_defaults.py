"""Security checks fail closed unless insecure dev mode is explicitly enabled."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app


def _client(monkeypatch, *, env: str, allow: str | None) -> TestClient:
    monkeypatch.setenv("RADIUS_ENV", env)
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(uuid4()))
    if allow is None:
        monkeypatch.delenv("RADIUS_ALLOW_INSECURE_DEV", raising=False)
    else:
        monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", allow)
    get_api_settings.cache_clear()
    return TestClient(create_app())


def _webhook(client: TestClient):
    return client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": str(uuid4())},
        content=b'{"zen": "hi"}',
    )


def _keyless_call(client: TestClient):
    return client.get(
        "/api/v1/repositories",
        headers={"X-Radius-Organization-Id": str(uuid4())},
    )


@pytest.mark.parametrize(
    ("env", "allow"),
    [
        ("development", None),
        ("development", "false"),
        ("uat", "true"),
        ("production", "true"),
    ],
)
def test_missing_secrets_are_rejected(monkeypatch, env, allow) -> None:
    client = _client(monkeypatch, env=env, allow=allow)

    assert _webhook(client).status_code in (401, 403)
    assert _keyless_call(client).status_code in (401, 403)


@pytest.mark.parametrize("env", ["development", "test"])
def test_explicit_dev_opt_in_allows_unsigned_and_keyless(monkeypatch, env) -> None:
    client = _client(monkeypatch, env=env, allow="true")

    assert _webhook(client).status_code == 202
    assert _keyless_call(client).status_code == 200
