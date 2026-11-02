"""Verdict v2 flag and route skeleton (VS-00, VD-07-lite): off by default, v1 untouched."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import ApiSettings, get_api_settings
from radius_api.main import create_app
from radius_shared.verdict_v2_flag import VerdictV2Mode


def test_alias_and_default_off() -> None:
    field = ApiSettings.model_fields["verdict_v2_mode"]
    assert field.alias == "RADIUS_FEATURE_VERDICT_V2"
    assert field.default is VerdictV2Mode.OFF


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, VerdictV2Mode.OFF),
        ("false", VerdictV2Mode.OFF),
        ("0", VerdictV2Mode.OFF),
        ("off", VerdictV2Mode.OFF),
        ("shadow", VerdictV2Mode.SHADOW),
        ("true", VerdictV2Mode.ON),
        ("1", VerdictV2Mode.ON),
        ("on", VerdictV2Mode.ON),
    ],
)
def test_environment_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.delenv("RADIUS_FEATURE_VERDICT_V2", raising=False)
    if raw is not None:
        monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", raw)
    assert ApiSettings().verdict_v2_mode is expected


def _client(monkeypatch, flag: str | None) -> TestClient:
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    monkeypatch.delenv("RADIUS_FEATURE_VERDICT_V2", raising=False)
    if flag is not None:
        monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", flag)
    get_api_settings.cache_clear()
    return TestClient(create_app())


def test_stub_route_is_404_disabled_when_flag_is_off(monkeypatch) -> None:
    client = _client(monkeypatch, None)
    response = client.get(
        f"/api/v1/analyses/{uuid4()}/verdict",
        headers={"X-Radius-Organization-Id": str(uuid4())},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["meta"]["reason"] == "disabled"


def test_unknown_analysis_is_404_not_found_when_flag_is_on(monkeypatch) -> None:
    client = _client(monkeypatch, "on")
    response = client.get(
        f"/api/v1/analyses/{uuid4()}/verdict-v2",
        headers={"X-Radius-Organization-Id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_v1_routes_and_openapi_are_unchanged_by_the_stub(monkeypatch) -> None:
    client = _client(monkeypatch, None)
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("verdict" in path for path in paths)
    assert any(path.endswith("/confidence") for path in paths)
