"""Single-tenant membership: RADIUS_DEFAULT_ORGANIZATION_ID and RADIUS_ADMIN_EMAILS.

With a default organization every signed-in user belongs to it (new users join it, users in an
empty auto-created personal workspace are moved at the next sign-in) and verified addresses on
RADIUS_ADMIN_EMAILS become admin. Without one, the personal-workspace behaviour is unchanged.
"""

from __future__ import annotations

import logging
import secrets
from uuid import UUID, uuid4

import pytest
from app import routes_auth
from app.auth import provision_domain_user_and_org, user_from_provider
from app.config import Settings, get_settings
from app.database import Base as AuthBase
from app.database import get_db
from app.models import User as AuthUser
from fastapi.testclient import TestClient
from pydantic import ValidationError
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.enums import UserRole
from radius_shared.database.models import Organization, Repository
from radius_shared.database.models import User as DomainUser
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_ORG, ADMINS = "RADIUS_DEFAULT_ORGANIZATION_ID", "RADIUS_ADMIN_EMAILS"
ADMIN = "owner@example.com"


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


@pytest.fixture
def db(factory):
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name in (
        "DEV_AUTO_VERIFY_EMAIL",
        "DEV_AUTO_VERIFY",
        "RADIUS_ENV",
        "RADIUS_SIGNUP_ALLOWED_EMAILS",
        "RADIUS_SIGNUP_ALLOWED_DOMAINS",
        DEFAULT_ORG,
        ADMINS,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    routes_auth._login_failures.clear()
    get_settings.cache_clear()
    yield
    routes_auth._login_failures.clear()
    get_settings.cache_clear()
    get_api_settings.cache_clear()


@pytest.fixture
def mails(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(routes_auth, "send_email_message", lambda to, *_: sent.append(to) or True)
    return sent


@pytest.fixture
def client(factory, mails):
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
def team(db) -> Organization:
    org = Organization(name="Radius Team")
    db.add(org)
    db.commit()
    return org


def _configure(monkeypatch, org: Organization | None, admins: str = "") -> None:
    if org is not None:
        monkeypatch.setenv(DEFAULT_ORG, str(org.id))
    else:
        monkeypatch.delenv(DEFAULT_ORG, raising=False)
    monkeypatch.setenv(ADMINS, admins)
    get_settings.cache_clear()


def _oauth(db, email: str, provider_id: str | None = None) -> AuthUser:
    return user_from_provider(
        db,
        provider="github",
        provider_id=provider_id or str(secrets.randbelow(10**8) + 1),
        email=email,
        name=email.split("@")[0].title(),
        email_verified=True,
    )


def _domain(db, email: str) -> DomainUser:
    db.expire_all()
    found = db.scalar(select(DomainUser).where(DomainUser.email == email))
    assert found is not None
    return found


def _workspaces(db) -> int:
    return db.scalar(
        select(func.count()).select_from(Organization).where(Organization.name.like("%'s Workspace"))
    )


# --- membership ---------------------------------------------------------------------------


def test_new_oauth_user_joins_default_org(monkeypatch, db, team) -> None:
    _configure(monkeypatch, team)
    user = _oauth(db, "dev@example.com")

    assert user.organization_id == str(team.id)
    member = _domain(db, "dev@example.com")
    assert member.organization_id == team.id
    assert member.role == UserRole.DEVELOPER
    assert user.role == "developer"
    assert _workspaces(db) == 0


def test_new_password_signup_joins_default_org(monkeypatch, client, db, team) -> None:
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    _configure(monkeypatch, team)
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": "New Dev", "email": "new@example.com", "password": _password()},
    )
    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == str(team.id)
    assert response.json()["role"] == "developer"
    assert _domain(db, "new@example.com").organization_id == team.id
    assert _workspaces(db) == 0


def test_existing_personal_workspace_user_moves_at_password_sign_in(
    monkeypatch, client, db, team
) -> None:
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    password = _password()
    _configure(monkeypatch, None)  # the account predates the setting
    created = client.post(
        "/api/v1/auth/signup",
        json={"name": "Early User", "email": "early@example.com", "password": password},
    )
    personal = UUID(created.json()["organization_id"])
    assert personal != team.id
    assert db.get(Organization, personal).name == "Early User's Workspace"

    _configure(monkeypatch, team)
    response = client.post(
        "/api/v1/auth/login", json={"email": "early@example.com", "password": password}
    )
    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == str(team.id)
    assert _domain(db, "early@example.com").organization_id == team.id
    assert client.get("/api/v1/auth/me").json()["organization_id"] == str(team.id)


def test_existing_personal_workspace_user_moves_at_oauth_sign_in(monkeypatch, db, team) -> None:
    _configure(monkeypatch, None)
    first = _oauth(db, "gh@example.com", provider_id="4242")
    assert first.organization_id != str(team.id)

    _configure(monkeypatch, team)
    again = _oauth(db, "gh@example.com", provider_id="4242")
    assert again.id == first.id
    assert again.organization_id == str(team.id)
    assert _domain(db, "gh@example.com").organization_id == team.id


def test_user_with_repositories_in_own_org_is_not_moved(monkeypatch, db, team, caplog) -> None:
    _configure(monkeypatch, None)
    user = _oauth(db, "busy@example.com", provider_id="5151")
    own = UUID(user.organization_id)
    db.add(
        Repository(
            organization_id=own,
            github_repository_id=777001,
            name="service",
            owner="busy",
            default_branch="main",
            clone_url="https://github.com/busy/service.git",
            visibility="private",
        )
    )
    db.commit()

    _configure(monkeypatch, team, admins="busy@example.com")
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        again = _oauth(db, "busy@example.com", provider_id="5151")
    assert again.organization_id == str(own)
    member = _domain(db, "busy@example.com")
    assert member.organization_id == own
    # admin is only granted in the default organization
    assert member.role == UserRole.DEVELOPER
    assert again.role == "developer"
    assert any("not moved" in r.getMessage() for r in caplog.records)
    assert "busy@example.com" not in caplog.text  # no personal data in the log


def test_shared_or_renamed_org_is_not_moved(monkeypatch, db, team) -> None:
    _configure(monkeypatch, None)
    alice = _oauth(db, "alice@example.com", provider_id="6161")
    shared = UUID(alice.organization_id)
    db.add(
        DomainUser(
            id=uuid4(), organization_id=shared, name="Bob", email="bob@example.com",
            role=UserRole.DEVELOPER,
        )
    )
    carol = _oauth(db, "carol@example.com", provider_id="6262")
    named = db.get(Organization, UUID(carol.organization_id))
    named.name = "Carol Corp"
    db.commit()

    _configure(monkeypatch, team)
    assert _oauth(db, "alice@example.com", provider_id="6161").organization_id == str(shared)
    assert _oauth(db, "carol@example.com", provider_id="6262").organization_id == str(named.id)


# --- admin role -----------------------------------------------------------------------------


def test_listed_verified_email_gets_admin(monkeypatch, db, team) -> None:
    _configure(monkeypatch, team, admins=f"other@example.com, {ADMIN.upper()}")
    user = _oauth(db, ADMIN)
    assert user.role == "admin"
    assert _domain(db, ADMIN).role == UserRole.ADMIN
    assert user.organization_id == str(team.id)


def test_listed_admin_is_promoted_when_moved(monkeypatch, db, team) -> None:
    _configure(monkeypatch, None, admins=ADMIN)  # ignored without a default organization
    first = _oauth(db, ADMIN, provider_id="7171")
    assert first.role == "developer"
    assert _domain(db, ADMIN).role == UserRole.DEVELOPER

    _configure(monkeypatch, team, admins=ADMIN)
    again = _oauth(db, ADMIN, provider_id="7171")
    assert again.organization_id == str(team.id)
    assert again.role == "admin"
    assert _domain(db, ADMIN).role == UserRole.ADMIN


def test_unlisted_user_stays_developer(monkeypatch, db, team) -> None:
    _configure(monkeypatch, team, admins=ADMIN)
    user = _oauth(db, "someone@example.com")
    assert user.role == "developer"
    assert _domain(db, "someone@example.com").role == UserRole.DEVELOPER


def test_unverified_listed_email_does_not_get_admin(monkeypatch, client, db, team) -> None:
    _configure(monkeypatch, team, admins=ADMIN)  # development: unverified signups get a session
    password = _password()
    response = client.post(
        "/api/v1/auth/signup", json={"name": "Owner", "email": ADMIN, "password": password}
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_verified"] is False
    assert response.json()["role"] == "developer"
    login = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "developer"
    assert _domain(db, ADMIN).role == UserRole.DEVELOPER

    # Once the address is proven, the next sign-in grants the role.
    db.expire_all()
    stored = db.scalar(select(AuthUser).where(AuthUser.email == ADMIN))
    stored.email_verified = True
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": password})
    assert login.json()["role"] == "admin"
    assert _domain(db, ADMIN).role == UserRole.ADMIN


def test_existing_admin_is_never_demoted(monkeypatch, db, team) -> None:
    _configure(monkeypatch, team, admins=ADMIN)
    _oauth(db, ADMIN, provider_id="8181")
    _configure(monkeypatch, team, admins="")  # removed from the list
    again = _oauth(db, ADMIN, provider_id="8181")
    assert again.role == "admin"
    assert _domain(db, ADMIN).role == UserRole.ADMIN


# --- no default organization / misconfiguration -----------------------------------------------


def test_without_default_org_users_get_personal_workspaces(monkeypatch, db, team) -> None:
    _configure(monkeypatch, None, admins=ADMIN)
    user = _oauth(db, ADMIN)
    org = db.get(Organization, UUID(user.organization_id))
    assert org.id != team.id
    assert org.name.endswith("'s Workspace")
    assert user.role == "developer"
    assert _domain(db, ADMIN).role == UserRole.DEVELOPER


def test_missing_default_org_falls_back_and_logs(monkeypatch, db, caplog) -> None:
    monkeypatch.setenv(DEFAULT_ORG, str(uuid4()))
    get_settings.cache_clear()
    with caplog.at_level(logging.ERROR, logger="app.auth"):
        user = _oauth(db, "lost@example.com")
    assert db.get(Organization, UUID(user.organization_id)).name.endswith("'s Workspace")
    assert any("does not exist" in r.getMessage() for r in caplog.records)


def test_provisioning_is_idempotent_in_default_org(monkeypatch, db, team) -> None:
    _configure(monkeypatch, team, admins=ADMIN)
    user = _oauth(db, ADMIN, provider_id="9191")
    provision_domain_user_and_org(db, user)
    provision_domain_user_and_org(db, user)
    count = db.scalar(select(func.count()).select_from(DomainUser).where(DomainUser.email == ADMIN))
    assert count == 1
    assert _workspaces(db) == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [(DEFAULT_ORG, "not-a-uuid"), (ADMINS, "owner"), (ADMINS, "@example.com")],
)
def test_invalid_settings_are_refused(monkeypatch, name, value) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_normalise_values(monkeypatch) -> None:
    org = uuid4()
    monkeypatch.setenv(DEFAULT_ORG, f" {str(org).upper()} ")
    monkeypatch.setenv(ADMINS, " Owner@Example.com ,owner@example.com")
    settings = Settings()
    assert settings.default_organization_id == str(org)
    assert settings.admin_emails == ADMIN
    assert settings.is_admin_email("OWNER@example.com")
    assert not settings.is_admin_email("other@example.com")
