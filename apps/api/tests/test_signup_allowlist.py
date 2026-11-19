"""R7: optional signup allowlist (RADIUS_SIGNUP_ALLOWED_EMAILS / RADIUS_SIGNUP_ALLOWED_DOMAINS).

OAuth provisioning under the allowlist is covered in ``test_oauth_flow.py``.
"""

from __future__ import annotations

import logging
import secrets

import pytest
from app import routes_auth
from app.config import Settings, get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import User as AuthUser
from fastapi.testclient import TestClient
from pydantic import ValidationError
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

EMAILS, DOMAINS = "RADIUS_SIGNUP_ALLOWED_EMAILS", "RADIUS_SIGNUP_ALLOWED_DOMAINS"


def _password() -> str:
    return "Aa1" + secrets.token_hex(8)  # built at run time: no credential literal


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    DomainBase.metadata.create_all(bind=engine)
    AuthBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name in ("DEV_AUTO_VERIFY_EMAIL", "DEV_AUTO_VERIFY", "RADIUS_ENV", EMAILS, DOMAINS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    routes_auth._login_failures.clear()
    get_settings.cache_clear()
    yield
    routes_auth._login_failures.clear()
    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _allow(monkeypatch, emails: str = "", domains: str = "") -> None:
    monkeypatch.setenv(EMAILS, emails)
    monkeypatch.setenv(DOMAINS, domains)
    get_settings.cache_clear()


@pytest.fixture
def mails(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(routes_auth, "send_email_message", lambda to, *_: sent.append(to) or True)
    return sent


def _client(factory) -> TestClient:
    app = create_app()

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


@pytest.fixture
def client(factory):
    with _client(factory) as test_client:
        yield test_client


@pytest.fixture
def production_like(monkeypatch, factory):
    monkeypatch.setenv("RADIUS_ENV", "uat")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(40))
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", secrets.token_urlsafe(40))
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "smtp")
    get_settings.cache_clear()
    get_api_settings.cache_clear()
    with _client(factory) as test_client:
        yield test_client


def _signup(client, email, password=None):
    return client.post(
        "/api/v1/auth/signup",
        json={"name": "Someone", "email": email, "password": password or _password()},
    )


def _users(factory) -> list[str]:
    with factory() as db:
        return [u.email for u in db.scalars(select(AuthUser))]


# ---------------------------------------------------------------- settings


def test_lists_are_normalised_and_matched_exactly(monkeypatch) -> None:
    _allow(monkeypatch, " Alice@Example.COM ,bob@example.com,alice@example.com", "Corp.Example.,")
    settings = get_settings()
    assert settings.signup_allowed_emails == "alice@example.com,bob@example.com"
    assert settings.signup_allowed_domains == "corp.example"
    assert settings.email_allowed("ALICE@example.com")
    assert settings.email_allowed("anyone@CORP.example")
    assert not settings.email_allowed("carol@example.com")
    assert not settings.email_allowed("dev@team.corp.example")  # no subdomain wildcard
    assert not settings.email_allowed("corp.example")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (EMAILS, "example.com"),
        (EMAILS, "@example.com"),
        (EMAILS, "alice@"),
        (EMAILS, "a@b@example.com"),
        (EMAILS, "alice@localhost"),
        (DOMAINS, "alice@example.com"),
        (DOMAINS, "*.example.com"),
        (DOMAINS, "localhost"),
    ],
)
def test_malformed_entries_are_refused_at_start_up(monkeypatch, name, value) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError, match=name):
        Settings()


def test_no_allowlist_allows_everyone(monkeypatch, client, mails) -> None:
    assert not get_settings().signup_allowlist_enabled
    assert get_settings().email_allowed("anyone@anywhere.example")
    assert _signup(client, "anyone@anywhere.example").status_code == 201


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(40))
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")


def test_production_without_an_allowlist_starts_with_a_warning(monkeypatch, caplog) -> None:
    _production_env(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings()
    assert any(EMAILS in r.getMessage() for r in caplog.records)
    caplog.clear()
    monkeypatch.setenv(DOMAINS, "example.com")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings()
    assert not any(EMAILS in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- development


def test_development_allows_listed_addresses_and_refuses_others_with_403(
    monkeypatch, client, factory, mails
) -> None:
    _allow(monkeypatch, emails="alice@example.com", domains="corp.example")
    assert _signup(client, "Alice@Example.com").status_code == 201
    assert _signup(client, "bob@corp.example").status_code == 201
    for refused_address in ("mallory@example.com", "dev@team.corp.example"):
        refused = _signup(client, refused_address)
        assert refused.status_code == 403
        assert "not allowed" in refused.json()["detail"]
    assert sorted(_users(factory)) == ["alice@example.com", "bob@corp.example"]
    assert "mallory@example.com" not in mails


def test_login_and_sessions_of_unlisted_accounts_are_refused(monkeypatch, client, mails) -> None:
    password = _password()
    assert _signup(client, "early@example.com", password).status_code == 201  # before the list
    assert client.get("/api/v1/auth/me").status_code == 200
    _allow(monkeypatch, domains="corp.example")

    assert client.get("/api/v1/auth/me").status_code == 401  # the old session is dead
    assert client.post("/api/v1/auth/refresh").status_code == 401
    refused = client.post(
        "/api/v1/auth/login", json={"email": "early@example.com", "password": password}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "early@example.com", "password": _password()}
    )
    assert refused.status_code == wrong.status_code == 401
    assert refused.json() == wrong.json()  # list membership is not revealed
    assert "radius_session" not in refused.headers.get("set-cookie", "")

    _allow(monkeypatch, emails="early@example.com")
    ok = client.post(
        "/api/v1/auth/login", json={"email": "early@example.com", "password": password}
    )
    assert ok.status_code == 200


# ---------------------------------------------------------------- uat / production


def test_production_like_refusal_answers_like_a_normal_signup_without_mail(
    monkeypatch, production_like, factory, mails
) -> None:
    _allow(monkeypatch, domains="corp.example")
    hashes: list[int] = []
    real_hash = routes_auth.hash_password
    monkeypatch.setattr(routes_auth, "hash_password", lambda v: hashes.append(1) or real_hash(v))

    allowed = _signup(production_like, "new@corp.example")
    refused = _signup(production_like, "outsider@example.com")

    assert allowed.status_code == refused.status_code == 201
    assert set(allowed.json()) == set(refused.json())
    body = refused.json()
    assert body["email"] == "outsider@example.com"
    assert body["email_verified"] is False and body["organization_id"] is None
    assert len(hashes) == 2  # the same password-hashing work
    assert mails == ["new@corp.example"]  # nothing is sent to the refused address
    assert _users(factory) == ["new@corp.example"]
    assert "radius_session" not in production_like.cookies
