"""B-07: the confirmer of a criterion is the authenticated principal, never a header."""

from __future__ import annotations

import secrets
from uuid import uuid4

import pytest
from app.auth import create_session
from app.config import get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import AuthAccount, AuthSession
from app.models import User as AuthUser
from fastapi.testclient import TestClient
from radius_api.auth import ApiPrincipal
from radius_api.config import get_api_settings
from radius_api.confirmer import SESSION_HEADER, resolve_actor
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BODY = "## Acceptance Criteria\n- Users must be able to reset their password\n"


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    DomainBase.metadata.create_all(bind=engine)
    AuthBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def world(factory, monkeypatch):
    org = str(uuid4())
    key = "k" + secrets.token_hex(12)
    monkeypatch.setenv("API_KEYS", f"{org}:{key}")
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_api_settings.cache_clear()
    get_settings.cache_clear()
    app = create_app()

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    base = {"X-Radius-Organization-Id": org, "X-Radius-API-Key": key}
    repo = client.post(
        "/api/v1/repositories",
        headers=base,
        json={
            "organizationId": org,
            "repositoryId": 4242,
            "name": "r",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    analysis = client.post(
        "/api/v1/analyses",
        headers=base,
        json={"repositoryId": repo, "pullRequestId": str(uuid4()), "commitSha": "a" * 40},
    ).json()["data"]["id"]
    sub = client.post(
        f"/api/v1/analyses/{analysis}/intent/sources",
        headers=base,
        json={"kind": "pr_body", "text": BODY},
    )
    assert sub.status_code in (200, 201), sub.text
    got = client.get(f"/api/v1/analyses/{analysis}/intent", headers=base)
    assert got.status_code == 200, got.text
    crit = got.json()["data"]["criteria"][0]["id"]
    yield client, base, analysis, crit, factory
    get_api_settings.cache_clear()
    get_settings.cache_clear()


def _make_user(factory, *, login: str | None):
    with factory() as db:
        user = AuthUser(name="Rev", email=f"{secrets.token_hex(4)}@example.com", email_verified=True)
        db.add(user)
        db.flush()
        if login is not None:
            db.add(
                AuthAccount(
                    user_id=user.id,
                    provider="github",
                    provider_account_id="12345",
                    provider_login=login,
                )
            )
        db.commit()
        token = create_session(db, user)
        return user.id, token


def _confirm(client, base, analysis, crit, **extra):
    return client.patch(
        f"/api/v1/analyses/{analysis}/intent/criteria/{crit}",
        headers={**base, **extra},
        json={"action": "confirm"},
    )


def _actor(client, base, analysis, crit) -> str:
    rows = client.get(
        f"/api/v1/analyses/{analysis}/intent/criteria/{crit}/history", headers=base
    ).json()["data"]
    return rows[-1]["actor"]


def test_session_user_with_a_github_link_is_recorded_with_the_login(world) -> None:
    client, base, analysis, crit, factory = world
    uid, token = _make_user(factory, login="octo-reviewer")

    response = _confirm(client, base, analysis, crit, **{SESSION_HEADER: token})

    assert response.status_code == 200, response.text
    org = base["X-Radius-Organization-Id"]
    assert _actor(client, base, analysis, crit) == f"org:{org}/user={uid}/gh=octo-reviewer"


def test_session_user_without_a_github_link_has_no_login(world) -> None:
    client, base, analysis, crit, factory = world
    uid, token = _make_user(factory, login=None)

    assert _confirm(client, base, analysis, crit, **{SESSION_HEADER: token}).status_code == 200

    org = base["X-Radius-Organization-Id"]
    assert _actor(client, base, analysis, crit) == f"org:{org}/user={uid}"


def test_a_client_supplied_actor_label_is_ignored(world) -> None:
    client, base, analysis, crit, _ = world

    response = _confirm(client, base, analysis, crit, **{"X-Radius-Actor": "someone-else"})

    assert response.status_code == 200
    org = base["X-Radius-Organization-Id"]
    assert _actor(client, base, analysis, crit) == f"org:{org}/legacy-env-key"


def test_a_label_cannot_forge_the_structured_actor(world) -> None:
    client, base, analysis, crit, _ = world

    for label in ("user=abc/gh=other", "gh=x"):
        response = _confirm(client, base, analysis, crit, **{"X-Radius-Actor": label})
        assert response.status_code == 422  # '=' and '/' are not label characters


def test_invalid_or_revoked_session_is_refused(world) -> None:
    client, base, analysis, crit, factory = world
    _, token = _make_user(factory, login="octo")

    bad = _confirm(client, base, analysis, crit, **{SESSION_HEADER: token + "x"})
    assert bad.status_code == 401

    with factory() as db:
        for row in db.query(AuthSession).all():
            row.revoked_at = row.created_at
        db.commit()
    revoked = _confirm(client, base, analysis, crit, **{SESSION_HEADER: token})
    assert revoked.status_code == 401


def test_a_managed_key_is_recorded_by_prefix_and_dev_keeps_its_label(factory) -> None:
    org = uuid4()
    with factory() as db:
        managed = ApiPrincipal(organization_id=org, source="managed", key_prefix="ab12cd")
        assert resolve_actor(managed, session_token=None, label="evil", auth_db=db) == (
            f"org:{org}/key=ab12cd"
        )
        dev = ApiPrincipal(organization_id=org, source="dev")
        assert resolve_actor(dev, session_token=None, label="me", auth_db=db) == (
            f"org:{org}/dev=me"
        )


def test_oauth_sign_in_records_and_refreshes_the_github_login(factory) -> None:
    from app.auth import user_from_provider

    with factory() as db:
        email = f"{secrets.token_hex(4)}@example.com"
        user = user_from_provider(
            db, "github", "777", email, "Octo", email_verified=True, login="octo-first"
        )
        account = db.query(AuthAccount).filter_by(user_id=user.id).one()
        assert account.provider_login == "octo-first"

        again = user_from_provider(
            db, "github", "777", email, "Octo", email_verified=True, login="octo-renamed"
        )
        assert again.id == user.id
        db.refresh(account)
        assert account.provider_login == "octo-renamed"
        # a sign-in that does not report a login never erases the stored one
        user_from_provider(db, "github", "777", email, "Octo", email_verified=True)
        db.refresh(account)
        assert account.provider_login == "octo-renamed"
