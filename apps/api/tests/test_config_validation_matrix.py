"""Configuration validation matrix: what each runtime environment accepts or rejects.

Covers the API HTTP-hardening settings (CORS) and the sign-in module settings
(session secret, e-mail delivery mode). Fake secrets are built at runtime.
"""

from __future__ import annotations

import secrets

import pytest
from app.config import KNOWN_PUBLIC_SESSION_SECRETS, Settings
from pydantic import ValidationError
from radius_api.config import ApiSettings
from radius_api.middleware.hardening import (
    LOCAL_DASHBOARD_ORIGINS,
    resolve_cors_origins,
)


def api_settings(monkeypatch: pytest.MonkeyPatch, env: str, cors: str = "") -> ApiSettings:
    monkeypatch.setenv("RADIUS_ENV", env)
    monkeypatch.setenv("CORS_ORIGINS", cors)
    return ApiSettings(_env_file=None)


def auth_settings(monkeypatch: pytest.MonkeyPatch, env: str, **values: str) -> Settings:
    monkeypatch.setenv("RADIUS_ENV", env)
    for key in ("SESSION_SECRET", "EMAIL_DELIVERY_MODE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key.upper(), value)
    return Settings(_env_file=None)


# ---------------------------------------------------------------- CORS matrix


@pytest.mark.parametrize(
    ("cors", "accepted"),
    [
        ("", True),
        ("https://dash.example.com", True),
        ("https://dash.example.com,https://other.example.com:8443", True),
        ("*", False),
        ("http://localhost:3000", False),
        ("http://dash.example.com", False),
        ("https://dash.example.com,http://localhost:3000", False),
        ("https://*.example.com", False),
        ("dash.example.com", False),
    ],
)
def test_production_cors_matrix(monkeypatch, cors: str, accepted: bool) -> None:
    if accepted:
        assert api_settings(monkeypatch, "production", cors).environment.value == "production"
    else:
        with pytest.raises(ValidationError):
            api_settings(monkeypatch, "production", cors)


@pytest.mark.parametrize("env", ["development", "test"])
@pytest.mark.parametrize(
    "cors",
    ["", "http://localhost:3000", "http://127.0.0.1:3000", "https://dash.example.com", "*"],
)
def test_development_and_test_accept_local_and_https_origins(monkeypatch, env, cors) -> None:
    assert api_settings(monkeypatch, env, cors).cors_origins == cors


@pytest.mark.parametrize("env", ["development", "test"])
def test_non_production_adds_localhost_origins(monkeypatch, env) -> None:
    origins = resolve_cors_origins(api_settings(monkeypatch, env))
    assert set(LOCAL_DASHBOARD_ORIGINS) <= set(origins)


def test_production_does_not_add_localhost_origins(monkeypatch) -> None:
    origins = resolve_cors_origins(
        api_settings(monkeypatch, "production", "https://dash.example.com")
    )
    assert origins == ["https://dash.example.com"]
    assert not set(LOCAL_DASHBOARD_ORIGINS) & set(origins)


def test_production_with_no_origins_allows_no_browser_origin(monkeypatch) -> None:
    assert resolve_cors_origins(api_settings(monkeypatch, "production")) == []


# ------------------------------------------------------- sign-in module matrix


def test_default_delivery_mode_is_smtp(monkeypatch) -> None:
    assert auth_settings(monkeypatch, "development").email_delivery_mode == "smtp"


@pytest.mark.parametrize("env", ["development", "test", "uat"])
def test_log_mode_accepted_outside_production(monkeypatch, env) -> None:
    settings = auth_settings(monkeypatch, env, email_delivery_mode="LOG")
    assert settings.email_delivery_mode == "log"


def test_log_mode_rejected_in_production(monkeypatch) -> None:
    secret = secrets.token_urlsafe(40)
    with pytest.raises(ValidationError, match="not allowed in production"):
        auth_settings(monkeypatch, "production", email_delivery_mode="log", session_secret=secret)


@pytest.mark.parametrize("mode", ["sendgrid", "console"])
def test_unknown_delivery_mode_rejected(monkeypatch, mode) -> None:
    with pytest.raises(ValidationError):
        auth_settings(monkeypatch, "development", email_delivery_mode=mode)


@pytest.mark.parametrize("secret", sorted(KNOWN_PUBLIC_SESSION_SECRETS))
def test_production_rejects_published_session_secrets(monkeypatch, secret) -> None:
    with pytest.raises(ValidationError, match="published placeholder"):
        auth_settings(monkeypatch, "production", session_secret=secret)


def test_production_rejects_unset_session_secret(monkeypatch) -> None:
    # Unset means the code default, which is a published literal.
    with pytest.raises(ValidationError):
        auth_settings(monkeypatch, "production")


def test_production_accepts_random_session_secret(monkeypatch) -> None:
    secret = secrets.token_urlsafe(40)
    assert auth_settings(monkeypatch, "production", session_secret=secret).session_secret == secret


def test_session_secret_must_be_at_least_32_chars(monkeypatch) -> None:
    with pytest.raises(ValidationError):
        auth_settings(monkeypatch, "development", session_secret="short")


def test_development_tolerates_published_session_secret(monkeypatch) -> None:
    assert auth_settings(monkeypatch, "development").session_secret in KNOWN_PUBLIC_SESSION_SECRETS
