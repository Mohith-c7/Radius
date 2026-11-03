"""Security review A (auth findings A-07..A-10, A-12, A-14..A-16): regression tests."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from app import routes_auth
from app.auth import (
    _may_log_action_tokens,
    consume_action_token,
    create_action_token,
    hash_password,
    should_auto_verify_email,
)
from app.config import Settings, get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import AuthSession, AuthToken
from app.models import User as AuthUser
from fastapi import HTTPException
from fastapi.testclient import TestClient
from radius_api.config import ApiSettings
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.enums import UserRole
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _password() -> str:
    # Built at run time: no literal credential-looking string in the repository.
    return "Aa1" + secrets.token_hex(8)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DomainBase.metadata.create_all(bind=engine)
    AuthBase.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(factory):
    session = factory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name in ("DEV_AUTO_VERIFY_EMAIL", "DEV_AUTO_VERIFY", "RADIUS_ENV"):
        monkeypatch.delenv(name, raising=False)
    # The per-IP auth limiter (10/min) would mask what these tests exercise.
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    getattr(routes_auth, "_login_failures", {}).clear()
    get_settings.cache_clear()
    yield
    getattr(routes_auth, "_login_failures", {}).clear()
    get_settings.cache_clear()


def _client(factory, monkeypatch=None) -> TestClient:
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
def mails(monkeypatch):
    sent: list[dict[str, str]] = []

    def fake_send(to_email, subject, text_body, html_body):
        sent.append(
            {"to": to_email, "subject": subject, "text": text_body, "html": html_body}
        )
        return True

    monkeypatch.setattr(routes_auth, "send_email_message", fake_send)
    return sent


def _signup(client, email="victim@example.com", name="Attacker", password=None):
    password = password or _password()
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    return response, password


def _token_from(mail: dict[str, str]) -> str:
    return mail["text"].split("token=")[1].split()[0]


# --- A-07 ---------------------------------------------------------------------


def test_verification_revokes_sessions_made_before_the_address_was_proven(
    client, mails
) -> None:
    response, _ = _signup(client)
    assert response.status_code == 201
    attacker_cookie = client.cookies.get("radius_session")
    assert attacker_cookie  # development/test: unverified signup still gets a session
    assert client.get("/api/v1/auth/me").status_code == 200

    victim = client.post(
        "/api/v1/auth/verify-email", json={"token": _token_from(mails[0])}
    )
    assert victim.status_code == 200

    client.cookies.set("radius_session", attacker_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_revokes_existing_sessions(client, mails) -> None:
    _signup(client)
    attacker_cookie = client.cookies.get("radius_session")
    assert client.get("/api/v1/auth/me").status_code == 200

    forgot = client.post(
        "/api/v1/auth/forgot-password", json={"email": "victim@example.com"}
    )
    assert forgot.status_code == 202
    reset_mail = [m for m in mails if "Reset" in m["subject"]][0]
    new_password = _password()
    done = client.post(
        "/api/v1/auth/reset-password",
        json={"token": _token_from(reset_mail), "password": new_password},
    )
    assert done.status_code == 204

    client.cookies.set("radius_session", attacker_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    fresh = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": new_password},
    )
    assert fresh.status_code == 200


@pytest.fixture
def production_like(monkeypatch, factory):
    """API app configured as uat/production: strict verification rules apply."""

    monkeypatch.setenv("RADIUS_ENV", "uat")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(40))
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", secrets.token_urlsafe(40))
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "smtp")
    get_settings.cache_clear()
    from radius_api.config import get_api_settings

    get_api_settings.cache_clear()
    with _client(factory) as test_client:
        yield test_client
    get_api_settings.cache_clear()


def test_production_like_signup_gets_no_session_and_cannot_sign_in_unverified(
    production_like, mails, db
) -> None:
    client = production_like
    response, password = _signup(client)
    assert response.status_code == 201
    assert "radius_session" not in client.cookies
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": password},
    )
    assert login.status_code == 403
    assert "radius_session" not in client.cookies


def test_production_like_signup_does_not_join_an_existing_organization(
    production_like, mails, db
) -> None:
    from radius_shared.database.models import Organization
    from radius_shared.database.models import User as DomainUser

    org = Organization(name="Victim Co")
    db.add(org)
    db.flush()
    domain_user = DomainUser(
        role=UserRole.DEVELOPER,
        organization_id=org.id,
        github_user_id=4242,
        name="Victim",
        email="victim@example.com",
    )
    db.add(domain_user)
    db.commit()

    response, _ = _signup(production_like)
    assert response.status_code == 201
    assert response.json()["organization_id"] is None


def test_production_like_verification_clears_the_pre_verification_password(
    production_like, mails, db
) -> None:
    client = production_like
    _, attacker_password = _signup(client)
    verified = client.post(
        "/api/v1/auth/verify-email", json={"token": _token_from(mails[0])}
    )
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True

    # The password the signer chose no longer works; the mailbox owner uses reset.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": attacker_password},
    )
    assert login.status_code == 401
    client.post("/api/v1/auth/forgot-password", json={"email": "victim@example.com"})
    reset_mail = [m for m in mails if "Reset" in m["subject"]][0]
    mine = _password()
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": _token_from(reset_mail), "password": mine},
        ).status_code
        == 204
    )
    ok = client.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": mine}
    )
    assert ok.status_code == 200
    assert ok.json()["organization_id"]


# --- A-08 ---------------------------------------------------------------------


def test_user_name_is_escaped_in_html_mail(client, mails) -> None:
    hostile = '<img src=x onerror=alert(1)><a href="https://evil.example">x</a>'
    _signup(client, name=hostile)
    html_body = mails[0]["html"]
    assert "<img" not in html_body
    assert 'href="https://evil.example"' not in html_body
    assert "&lt;img" in html_body

    client.post("/api/v1/auth/forgot-password", json={"email": "victim@example.com"})
    assert all("<img" not in m["html"] for m in mails)

    client.post("/api/v1/auth/resend-verification")
    assert all("<img" not in m["html"] for m in mails)


# --- A-10 ---------------------------------------------------------------------


def test_missing_session_row_is_401_not_500(factory, db) -> None:
    with _client(factory) as client:
        password = _password()
        db.add(
            AuthUser(
                name="N",
                email="gone@example.com",
                password_hash=hash_password(password),
                email_verified=True,
            )
        )
        db.commit()
        login = client.post(
            "/api/v1/auth/login", json={"email": "gone@example.com", "password": password}
        )
        assert login.status_code == 200
        for row in db.scalars(select(AuthSession)).all():
            db.delete(row)
        db.commit()
        assert client.get("/api/v1/auth/me").status_code == 401


# --- A-12 ---------------------------------------------------------------------


def test_unknown_account_login_spends_a_password_hash(client, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(routes_auth, "burn_password_check", lambda pw: calls.append(pw))
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": _password()},
    )
    assert response.status_code == 401
    assert len(calls) == 1


def test_login_is_throttled_per_account_after_repeated_failures(
    client, db
) -> None:
    good = _password()
    db.add(
        AuthUser(
            name="T",
            email="target@example.com",
            password_hash=hash_password(good),
            email_verified=True,
        )
    )
    db.commit()
    for _ in range(routes_auth._LOGIN_FAILURE_LIMIT):
        bad = client.post(
            "/api/v1/auth/login",
            json={"email": "target@example.com", "password": _password()},
        )
        assert bad.status_code == 401
    locked = client.post(
        "/api/v1/auth/login", json={"email": "target@example.com", "password": good}
    )
    assert locked.status_code == 429
    # Another account is unaffected by the target's failures.
    other = client.post(
        "/api/v1/auth/login",
        json={"email": "someone-else@example.com", "password": _password()},
    )
    assert other.status_code == 401


def test_login_does_not_apply_the_signup_password_policy(client, db) -> None:
    db.add(
        AuthUser(
            name="Old",
            email="old@example.com",
            password_hash=hash_password("simple"),
            email_verified=True,
        )
    )
    db.commit()
    response = client.post(
        "/api/v1/auth/login", json={"email": "old@example.com", "password": "simple"}
    )
    assert response.status_code == 200


# --- A-14 ---------------------------------------------------------------------


def test_action_token_is_single_use_even_when_a_concurrent_reader_saw_it_unused(
    db, factory
) -> None:
    user = AuthUser(name="U", email="race@example.com", email_verified=False)
    db.add(user)
    db.commit()
    raw = create_action_token(db, user.id, "reset_password")

    other = factory()
    try:
        stale = other.scalar(select(AuthToken))  # a second request read it unused
        assert stale is not None and stale.used_at is None
        assert consume_action_token(db, raw, "reset_password").id == user.id

        class _StaleReader:
            """Session proxy whose first select still returns the pre-use row."""

            def __init__(self, real):
                self._real = real
                self._served = False

            def scalar(self, *args, **kwargs):
                if not self._served:
                    self._served = True
                    return stale
                return self._real.scalar(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        with pytest.raises(HTTPException) as excinfo:
            consume_action_token(_StaleReader(other), raw, "reset_password")
        assert excinfo.value.status_code == 400
    finally:
        other.close()


def test_action_token_expired_and_unknown_are_rejected(db) -> None:
    user = AuthUser(name="U", email="exp@example.com")
    db.add(user)
    db.commit()
    raw = create_action_token(db, user.id, "verify_email", minutes=1)
    row = db.scalar(select(AuthToken))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    for token in (raw, "x" * 40):
        with pytest.raises(HTTPException):
            consume_action_token(db, token, "verify_email")


# --- A-15 ---------------------------------------------------------------------


def test_refresh_rotates_the_session(client, db) -> None:
    password = _password()
    db.add(
        AuthUser(
            name="R",
            email="rot@example.com",
            password_hash=hash_password(password),
            email_verified=True,
        )
    )
    db.commit()
    client.post(
        "/api/v1/auth/login",
        json={"email": "rot@example.com", "password": password, "remember": True},
    )
    first = client.cookies.get("radius_session")
    assert client.post("/api/v1/auth/refresh").status_code == 200
    second = client.cookies.get("radius_session")
    assert second and second != first

    client.cookies.set("radius_session", first)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("radius_session", second)
    assert client.get("/api/v1/auth/me").status_code == 200

    live = db.scalars(select(AuthSession).where(AuthSession.revoked_at.is_(None))).all()
    assert len(live) == 1
    created = live[0].created_at
    expires = live[0].expires_at
    created = created if created.tzinfo else created.replace(tzinfo=UTC)
    expires = expires if expires.tzinfo else expires.replace(tzinfo=UTC)
    assert (expires - created) > timedelta(days=20)  # "remember me" survives refresh


def test_refresh_without_a_session_is_401(client) -> None:
    assert client.post("/api/v1/auth/refresh").status_code == 401


# --- A-16 / A-09 -----------------------------------------------------------------


def test_dev_auto_verify_is_ignored_in_production_like_environments(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    monkeypatch.setenv("RADIUS_ENV", "uat")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    # Settings refuses to start with the switch set ...
    with pytest.raises(ValueError):
        Settings()
    # ... and even if something constructed settings anyway the function says no.
    monkeypatch.delenv("DEV_AUTO_VERIFY_EMAIL")
    get_settings.cache_clear()
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    monkeypatch.setattr(
        "app.auth.get_settings", lambda: Settings.model_construct(runtime_env="uat")
    )
    assert should_auto_verify_email() is False


def test_dev_auto_verify_still_works_in_development(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ENV", "development")
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    get_settings.cache_clear()
    assert should_auto_verify_email() is True


def test_action_links_are_not_logged_in_a_production_like_or_unlabelled_deployment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(40))
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    # RADIUS_ENV unset but a real secret configured: assume a real deployment.
    assert _may_log_action_tokens() is False
    monkeypatch.setenv("RADIUS_ENV", "production")
    get_settings.cache_clear()
    assert _may_log_action_tokens() is False
    monkeypatch.setenv("RADIUS_ENV", "development")
    get_settings.cache_clear()
    assert _may_log_action_tokens() is True


@pytest.mark.parametrize("env", ["production", "uat"])
def test_insecure_session_cookies_are_refused_in_production_like_modes(env) -> None:
    secret = secrets.token_urlsafe(40)
    with pytest.raises(ValueError):
        Settings(
            runtime_env=env, session_secret=secret, session_cookie_secure=False
        )
    assert Settings(
        runtime_env=env, session_secret=secret, session_cookie_secure=True
    )
    # development keeps working over plain http
    assert Settings(runtime_env="development", session_cookie_secure=False)


@pytest.mark.parametrize("env", ["production", "uat"])
def test_api_refuses_to_start_without_any_api_credentials(env) -> None:
    with pytest.raises(ValueError):
        ApiSettings(RADIUS_ENV=env, api_keys="", RADIUS_API_KEY_PEPPER="")
    assert ApiSettings(
        RADIUS_ENV=env, RADIUS_API_KEY_PEPPER=secrets.token_urlsafe(40)
    )
    assert ApiSettings(RADIUS_ENV="development")


def test_compose_forwards_the_api_key_pepper_and_secure_cookies() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "RADIUS_API_KEY_PEPPER: ${RADIUS_API_KEY_PEPPER:-}" in text
    assert "SESSION_COOKIE_SECURE: ${SESSION_COOKIE_SECURE:-true}" in text
