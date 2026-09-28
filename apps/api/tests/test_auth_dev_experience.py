"""Tests for Auth Developer Experience & Domain User Provisioning."""

from uuid import UUID

import pytest
from app.auth import (
    create_action_token,
    hash_password,
    should_auto_verify_email,
    user_from_provider,
)
from app.database import Base as AuthBase
from app.database import get_db
from app.models import User as AuthUser
from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.enums import UserRole
from radius_shared.database.models import Organization, Repository
from radius_shared.database.models import User as DomainUser
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def test_db_engine():
    """Create an isolated in-memory SQLite engine with all auth and domain tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DomainBase.metadata.create_all(bind=engine)
    AuthBase.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_db(test_db_engine):
    """Provide a transactional database session for tests."""
    testing_session_factory = sessionmaker(
        bind=test_db_engine, autocommit=False, autoflush=False
    )
    db = testing_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_client(test_db_engine):
    """Create a TestClient with dependency override pointing to test_db_engine."""
    app = create_app()
    testing_session_factory = sessionmaker(
        bind=test_db_engine, autocommit=False, autoflush=False
    )

    def override_get_db():
        db = testing_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Dev-Mode Logging Tests
# ==============================================================================


def test_create_action_token_logs_verification_url(capsys, test_db):
    """Verify that create_action_token outputs the expected dev URL format for email verification."""
    user = AuthUser(
        name="Developer One",
        email="dev1@example.com",
        password_hash=hash_password("Password123!"),
    )
    test_db.add(user)
    test_db.commit()

    token = create_action_token(test_db, user.id, "verify_email")
    captured = capsys.readouterr()

    expected_log = f"[DEV AUTH] Action Token for dev1@example.com (verify_email): http://localhost:3000/verify-email?token={token}"
    assert expected_log in captured.out


def test_create_action_token_logs_reset_password_url(capsys, test_db):
    """Verify that create_action_token outputs the expected dev URL format for password reset."""
    user = AuthUser(
        name="Developer Two",
        email="dev2@example.com",
        password_hash=hash_password("Password123!"),
    )
    test_db.add(user)
    test_db.commit()

    token = create_action_token(test_db, user.id, "reset_password")
    captured = capsys.readouterr()

    expected_log = f"[DEV AUTH] Action Token for dev2@example.com (reset_password): http://localhost:3000/reset-password?token={token}"
    assert expected_log in captured.out


def test_signup_endpoint_logs_dev_token(capsys, test_client):
    """Verify that calling the signup endpoint prints the dev action token link."""
    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Local Dev",
            "email": "localdev@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    captured = capsys.readouterr()

    assert (
        "[DEV AUTH] Action Token for localdev@example.com (verify_email): http://localhost:3000/verify-email?token="
        in captured.out
    )


def test_forgot_password_endpoint_logs_dev_token(capsys, test_client, test_db):
    """Verify that calling forgot-password logs the reset dev token link."""
    user = AuthUser(
        name="Reset Dev",
        email="resetdev@example.com",
        password_hash=hash_password("Password123!"),
    )
    test_db.add(user)
    test_db.commit()

    response = test_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "resetdev@example.com"},
    )
    assert response.status_code == 202
    captured = capsys.readouterr()

    assert (
        "[DEV AUTH] Action Token for resetdev@example.com (reset_password): http://localhost:3000/reset-password?token="
        in captured.out
    )


# ==============================================================================
# 2. Dev Auto-Verification Tests
# ==============================================================================


def test_should_auto_verify_email_resolution(monkeypatch):
    """Test resolution logic for DEV_AUTO_VERIFY_EMAIL and RADIUS_ENV."""
    # When no dev flags are set
    monkeypatch.delenv("DEV_AUTO_VERIFY_EMAIL", raising=False)
    monkeypatch.delenv("RADIUS_ENV", raising=False)
    monkeypatch.delenv("DEV_AUTO_VERIFY", raising=False)
    assert should_auto_verify_email() is False

    # Explicit DEV_AUTO_VERIFY_EMAIL
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")
    assert should_auto_verify_email() is True
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "1")
    assert should_auto_verify_email() is True
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "false")
    assert should_auto_verify_email() is False

    # RADIUS_ENV == development
    monkeypatch.delenv("DEV_AUTO_VERIFY_EMAIL", raising=False)
    monkeypatch.setenv("RADIUS_ENV", "development")
    assert should_auto_verify_email() is True

    # RADIUS_ENV == development with explicit DEV_AUTO_VERIFY=false
    monkeypatch.setenv("DEV_AUTO_VERIFY", "false")
    assert should_auto_verify_email() is False


def test_signup_auto_verify_disabled_by_default(monkeypatch, test_client, test_db):
    """Verify email_verified is False upon signup when dev auto-verify is inactive."""
    monkeypatch.delenv("DEV_AUTO_VERIFY_EMAIL", raising=False)
    monkeypatch.delenv("RADIUS_ENV", raising=False)

    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Standard User",
            "email": "standard@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email_verified"] is False

    user = test_db.scalar(
        select(AuthUser).where(AuthUser.email == "standard@example.com")
    )
    assert user.email_verified is False


def test_signup_auto_verify_enabled_with_env_flag(monkeypatch, test_client, test_db):
    """Verify email_verified is True immediately upon signup when DEV_AUTO_VERIFY_EMAIL=true."""
    monkeypatch.setenv("DEV_AUTO_VERIFY_EMAIL", "true")

    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Dev User",
            "email": "devuser@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email_verified"] is True

    user = test_db.scalar(
        select(AuthUser).where(AuthUser.email == "devuser@example.com")
    )
    assert user.email_verified is True


def test_signup_auto_verify_enabled_with_radius_env(monkeypatch, test_client, test_db):
    """Verify email_verified is True immediately upon signup when RADIUS_ENV=development."""
    monkeypatch.delenv("DEV_AUTO_VERIFY_EMAIL", raising=False)
    monkeypatch.setenv("RADIUS_ENV", "development")

    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Dev Radius",
            "email": "devradius@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email_verified"] is True


# ==============================================================================
# 3. Domain User & Organization Provisioning Tests
# ==============================================================================


def test_signup_provisions_domain_organization_and_user(test_client, test_db):
    """Verify domain Organization and User records are created in shared schema on signup."""
    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Alice Smith",
            "email": "alice@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    auth_user_id = data["id"]
    org_id_str = data["organization_id"]
    assert org_id_str is not None

    org_id = UUID(org_id_str)

    # 1. Organization verification
    org = test_db.get(Organization, org_id)
    assert org is not None
    assert org.name == "Alice Smith's Workspace"
    assert org.slug == "alice-smith-s-workspace"

    # 2. Domain User verification
    domain_user = test_db.scalar(
        select(DomainUser).where(DomainUser.email == "alice@example.com")
    )
    assert domain_user is not None
    assert domain_user.organization_id == org_id
    assert domain_user.name == "Alice Smith"
    assert domain_user.role == UserRole.DEVELOPER
    assert domain_user.github_user_id is not None

    # 3. Auth user foreign/linked organization verification
    auth_user = test_db.get(AuthUser, auth_user_id)
    assert auth_user.organization_id == org_id_str


def test_domain_org_provisioning_usable_for_repositories(test_client, test_db):
    """Verify that the provisioned organization ID can be used immediately with foreign key constraints."""
    response = test_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Repo Tester",
            "email": "repotest@example.com",
            "password": "ValidPassword123!",
        },
    )
    assert response.status_code == 201
    org_id = UUID(response.json()["organization_id"])

    # Attempt to insert a Repository referencing the newly provisioned organization
    repo = Repository(
        organization_id=org_id,
        github_repository_id=987654,
        name="test-repo",
        owner="Repo Tester",
        default_branch="main",
        clone_url="https://github.com/repotest/test-repo.git",
        visibility="public",
    )
    test_db.add(repo)
    test_db.commit()

    saved_repo = test_db.scalar(
        select(Repository).where(Repository.organization_id == org_id)
    )
    assert saved_repo is not None
    assert saved_repo.name == "test-repo"
    assert saved_repo.organization.name == "Repo Tester's Workspace"


def test_user_from_provider_provisions_domain_models(test_db):
    """Verify that OAuth user_from_provider properly provisions domain org and user."""
    auth_user = user_from_provider(
        test_db,
        provider="github",
        provider_id="12345678",
        email="oauthdev@example.com",
        name="GitHub Developer",
    )
    assert auth_user is not None
    assert auth_user.organization_id is not None

    org_id = UUID(auth_user.organization_id)
    org = test_db.get(Organization, org_id)
    assert org is not None
    assert org.name == "GitHub Developer's Workspace"

    domain_user = test_db.scalar(
        select(DomainUser).where(DomainUser.email == "oauthdev@example.com")
    )
    assert domain_user is not None
    assert domain_user.organization_id == org_id
    assert domain_user.github_user_id == 12345678

    # Calling user_from_provider again returns existing user without creating duplicates
    re_auth_user = user_from_provider(
        test_db,
        provider="github",
        provider_id="12345678",
        email="oauthdev@example.com",
        name="GitHub Developer",
    )
    assert re_auth_user.id == auth_user.id

    all_orgs = test_db.scalars(
        select(Organization).where(Organization.name == "GitHub Developer's Workspace")
    ).all()
    assert len(all_orgs) == 1
