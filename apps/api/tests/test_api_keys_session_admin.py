"""/api/v1/api-keys: a dashboard session (X-Radius-Session) must belong to an organization admin.

The dashboard proxy sends its own key, which has every scope, so for a request that carries a
signed-in user's session the admin scope alone is not enough. Requests without a session
(automation) keep the admin-scope rule.
"""

from __future__ import annotations

import secrets
from uuid import UUID

import pytest
from app.auth import create_session, revoke_user_sessions
from app.config import get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import User as AuthUser
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.enums import UserRole
from radius_shared.database.models import Organization
from radius_shared.database.models import User as DomainUser
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PEPPER = "pepper-" + "y" * 40
ORG = UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_ORG = UUID("00000000-0000-4000-8000-0000000000c2")
LEGACY_KEY = "legacy" + "-" + "q" * 24


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DomainBase.metadata.create_all(bind=engine)
    AuthBase.metadata.create_all(bind=engine)
    make = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with make() as db:
        db.add_all(
            [
                Organization(id=ORG, name="Team"),
                Organization(id=OTHER_ORG, name="Other"),
            ]
        )
        db.commit()
    return make


@pytest.fixture
def client(factory, monkeypatch):
    monkeypatch.setenv("RADIUS_ENV", "development")
    monkeypatch.setenv("API_KEYS", f"{ORG}:{LEGACY_KEY},{OTHER_ORG}:{LEGACY_KEY}x")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "false")
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_api_settings.cache_clear()
    get_settings.cache_clear()
    app = create_app()

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    get_api_settings.cache_clear()
    get_settings.cache_clear()


def _session(factory, role: UserRole, org: UUID = ORG) -> str:
    """A signed-in user who is a member of ``org`` with ``role``; returns the session token."""
    with factory() as db:
        email = f"{secrets.token_hex(4)}@example.com"
        user = AuthUser(name="U", email=email, email_verified=True, role=role.value)
        db.add(user)
        db.flush()
        db.add(
            DomainUser(
                id=UUID(user.id), organization_id=org, name="U", email=email, role=role
            )
        )
        db.commit()
        return create_session(db, user)


def _headers(
    key: str = LEGACY_KEY, session: str | None = None, org: UUID = ORG
) -> dict:
    headers = {"X-Radius-Organization-Id": str(org), "X-Radius-API-Key": key}
    if session is not None:
        headers["X-Radius-Session"] = session
    return headers


def _new_key(client, scopes=("read",)) -> dict:
    created = client.post(
        "/api/v1/api-keys",
        headers=_headers(),
        json={"name": "k", "scopes": list(scopes)},
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _calls(key_id: str) -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", "/api/v1/api-keys", None),
        ("POST", "/api/v1/api-keys", {"name": "n", "scopes": ["read"]}),
        ("GET", "/api/v1/api-keys/audit", None),
        ("POST", f"/api/v1/api-keys/{key_id}/rotate", {"overlap_seconds": 0}),
        ("DELETE", f"/api/v1/api-keys/{key_id}", None),
    ]


def test_developer_session_is_refused_on_every_route(client, factory) -> None:
    key_id = _new_key(client)["key"]["id"]
    token = _session(factory, UserRole.DEVELOPER)
    for method, path, body in _calls(key_id):
        response = client.request(
            method, path, headers=_headers(session=token), json=body
        )
        assert response.status_code == 403, (method, path, response.text)
    # nothing was changed by the refused calls
    rows = client.get("/api/v1/api-keys", headers=_headers()).json()["data"]
    assert [r["id"] for r in rows] == [key_id] and rows[0]["revoked_at"] is None


def test_admin_session_is_allowed_on_every_route(client, factory) -> None:
    key_id = _new_key(client)["key"]["id"]
    token = _session(factory, UserRole.ADMIN)
    expected = {"GET": 200, "POST": 201, "DELETE": 200}
    for method, path, body in _calls(key_id):
        response = client.request(
            method, path, headers=_headers(session=token), json=body
        )
        assert response.status_code == expected[method], (method, path, response.text)
    audit = client.get("/api/v1/api-keys/audit", headers=_headers()).json()["data"]
    by_session = [e["actor"] for e in audit if "/user=" in e["actor"]]
    assert by_session and all(a.startswith("legacy-env-key/user=") for a in by_session)


def test_admin_of_another_organization_is_refused(client, factory) -> None:
    token = _session(factory, UserRole.ADMIN, org=OTHER_ORG)
    response = client.get("/api/v1/api-keys", headers=_headers(session=token))
    assert response.status_code == 403


def test_invalid_or_revoked_session_is_refused(client, factory) -> None:
    assert (
        client.get("/api/v1/api-keys", headers=_headers(session="a.b.c")).status_code
        == 403
    )
    token = _session(factory, UserRole.ADMIN)
    with factory() as db:
        user = db.query(AuthUser).filter(AuthUser.role == "admin").one()
        revoke_user_sessions(db, user.id)
        db.commit()
    assert (
        client.get("/api/v1/api-keys", headers=_headers(session=token)).status_code
        == 403
    )


def test_auth_user_admin_without_org_membership_is_refused(client, factory) -> None:
    with factory() as db:
        user = AuthUser(
            name="U", email="lone@example.com", email_verified=True, role="admin"
        )
        db.add(user)
        db.commit()
        token = create_session(db, user)
    assert (
        client.get("/api/v1/api-keys", headers=_headers(session=token)).status_code
        == 403
    )


def test_no_session_with_admin_scope_key_is_allowed(client) -> None:
    admin = _new_key(client, scopes=("admin",))
    assert (
        client.get("/api/v1/api-keys", headers=_headers()).status_code == 200
    )  # legacy key
    listed = client.get("/api/v1/api-keys", headers=_headers(key=admin["token"]))
    assert listed.status_code == 200


def test_no_session_with_read_scope_key_is_refused(client) -> None:
    reader = _new_key(client, scopes=("read",))
    response = client.get("/api/v1/api-keys", headers=_headers(key=reader["token"]))
    assert response.status_code == 403


def test_admin_session_does_not_lift_a_missing_scope(client, factory) -> None:
    reader = _new_key(client, scopes=("read",))
    token = _session(factory, UserRole.ADMIN)
    response = client.get(
        "/api/v1/api-keys", headers=_headers(key=reader["token"], session=token)
    )
    assert response.status_code == 403


def test_session_header_is_not_needed_elsewhere(client, factory) -> None:
    token = _session(factory, UserRole.DEVELOPER)
    response = client.get("/api/v1/repositories", headers=_headers(session=token))
    assert response.status_code == 200
