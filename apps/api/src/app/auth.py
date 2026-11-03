"""Authentication services: password hashing, signed sessions, and opaque action tokens."""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, status
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.enums import UserRole
from radius_shared.database.models import Organization
from radius_shared.database.models import User as DomainUser
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import KNOWN_PUBLIC_SESSION_SECRETS, get_settings
from .models import AuthAccount, AuthSession, AuthToken, User
from .oauth import OAuthError

password_hasher = PasswordHasher()
SESSION_TTL = timedelta(days=14)


_PRODUCTION_LIKE = frozenset({"production", "uat"})


def is_production_like() -> bool:
    """True for ``RADIUS_ENV`` production/uat (the settings object, not the raw env)."""
    return get_settings().runtime_env.strip().lower() in _PRODUCTION_LIKE


def should_auto_verify_email() -> bool:
    """Return True if email auto-verification is enabled for local dev.

    Never in production/uat: there a verified address must really have been
    proven (A-16). ``Settings`` additionally refuses to start with the switch set.
    """
    if is_production_like():
        return False
    dev_auto_verify = os.environ.get("DEV_AUTO_VERIFY_EMAIL")
    if dev_auto_verify is not None:
        return dev_auto_verify.lower() in ("true", "1", "yes")
    if os.environ.get("RADIUS_ENV") == "development":
        return os.environ.get("DEV_AUTO_VERIFY", "true").lower() in ("true", "1", "yes")
    return False


def _may_log_action_tokens() -> bool:
    """Action-token links are bearer credentials: log them only for local dev.

    Allowed when EMAIL_DELIVERY_MODE=log or the environment is not
    production/uat. Never written in a production-like deployment.
    """
    if get_settings().email_delivery_mode == "log":
        return True
    settings = get_settings()
    declared = os.environ.get("RADIUS_ENV", "").strip().lower()
    if declared:
        return declared not in _PRODUCTION_LIKE
    # RADIUS_ENV is not set at all (A-16). Treat that as development only while the
    # published placeholder session secret is still in use; a deployment that
    # configured a real secret but forgot RADIUS_ENV must not print login links.
    return settings.session_secret in KNOWN_PUBLIC_SESSION_SECRETS


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Spend the same argon2 time as a real check (unknown email, no password set).

    Keeps the response time of ``login`` from revealing whether an account exists.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = password_hasher.hash(secrets.token_urlsafe(16))
    verify_password(password, _dummy_hash)


def revoke_user_sessions(db: Session, user_id: str) -> int:
    """Revoke every live session of a user (call after a credential/ownership change)."""
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session(db: Session, user: User, remember: bool = False) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + (timedelta(days=30) if remember else SESSION_TTL)
    session = AuthSession(user_id=user.id, expires_at=expires.replace(tzinfo=None))
    db.add(session)
    db.commit()
    return jwt.encode(
        {"sub": user.id, "sid": session.id, "exp": expires, "type": "session"},
        settings.session_secret,
        algorithm="HS256",
    )


def decode_session(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
        if payload.get("type") != "session":
            raise jwt.InvalidTokenError
        return str(payload["sub"]), str(payload["sid"])
    except jwt.PyJWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please sign in again.",
        ) from error


def create_action_token(
    db: Session, user_id: str, purpose: str, minutes: int = 60
) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    db.commit()
    user = db.get(User, user_id)
    email = user.email if user else "unknown"
    path = "verify-email" if "verify" in purpose else "reset-password"
    if _may_log_action_tokens():
        print(
            f"[DEV AUTH] Action Token for {email} ({purpose}): http://localhost:3000/{path}?token={raw_token}"
        )
    return raw_token


def _usable_token(db: Session, raw_token: str, purpose: str) -> AuthToken:
    """The live (unused, unexpired) token row, or the generic 400."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == token_hash, AuthToken.purpose == purpose
        )
    )
    now = datetime.now(UTC)
    expires_at = (
        token.expires_at
        if token and token.expires_at.tzinfo is not None
        else (token.expires_at.replace(tzinfo=UTC) if token else None)
    )
    if (
        token is None
        or token.used_at is not None
        or (expires_at is not None and expires_at < now)
    ):
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    return token


def peek_action_token(db: Session, raw_token: str, purpose: str) -> User:
    """The user a live token belongs to, WITHOUT using the token up (A-07: the verify page
    asks whether a password is needed before the one-time token is spent)."""
    token = _usable_token(db, raw_token, purpose)
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    return user


def consume_action_token(db: Session, raw_token: str, purpose: str) -> User:
    token = _usable_token(db, raw_token, purpose)
    # Atomic single use (A-14): only the request whose UPDATE flips used_at from
    # NULL wins; a concurrent request with the same token matches no row.
    claimed = db.execute(
        update(AuthToken)
        .where(AuthToken.id == token.id, AuthToken.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    user = db.get(User, token.user_id)
    db.commit()
    if user is None:
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    return user


def provision_domain_user_and_org(
    db: Session,
    user: User,
    github_user_id: int | None = None,
) -> tuple[Organization, DomainUser]:
    """Check if domain User and Organization exist in the shared schema, creating them if not."""
    try:
        DomainBase.metadata.create_all(bind=db.get_bind(), checkfirst=True)
    except Exception:
        pass

    domain_user = db.scalar(
        select(DomainUser).where(DomainUser.email == user.email.lower())
    )

    org: Organization | None = None
    if domain_user is not None and domain_user.organization_id is not None:
        org = db.get(Organization, domain_user.organization_id)

    if org is None:
        clean_name = (user.name or "").strip() or user.email.split("@")[0]
        workspace_name = f"{clean_name}'s Workspace"
        org = Organization(name=workspace_name)
        db.add(org)
        db.flush()

    if domain_user is None:
        try:
            user_uuid = UUID(str(user.id))
        except (ValueError, TypeError, AttributeError):
            user_uuid = uuid4()

        # C-15: password users have no GitHub id; store NULL (the column is
        # nullable) instead of a number fabricated from the e-mail address.

        role = (
            UserRole.ADMIN
            if getattr(user, "role", "") == "admin"
            else UserRole.DEVELOPER
        )
        domain_user = DomainUser(
            id=user_uuid,
            organization_id=org.id,
            github_user_id=github_user_id,
            name=user.name or user.email.split("@")[0],
            email=user.email.lower(),
            role=role,
        )
        db.add(domain_user)
    elif domain_user.organization_id != org.id:
        domain_user.organization_id = org.id

    if hasattr(user, "organization_id") and (
        not user.organization_id or user.organization_id != str(org.id)
    ):
        user.organization_id = str(org.id)

    db.commit()
    db.refresh(org)
    db.refresh(domain_user)
    return org, domain_user


def user_from_provider(
    db: Session,
    provider: str,
    provider_id: str,
    email: str,
    name: str,
    *,
    email_verified: bool = False,
    login: str | None = None,
) -> User:
    """Resolve the local user for an OAuth identity.

    Policy (docs/security/SSO_DESIGN.md):

    1. ``(provider, provider_id)`` (the stable ``sub``) is the identity key and is looked up
       first; the email is never consulted for a known identity.
    2. An unknown identity is only trusted with an email the provider asserts is verified.
    3. An existing local account with the same email is linked only when its own email was
       verified too. Otherwise the link is refused (``oauth_link_refused``): linking an
       unverified local account would hand it to whoever registered that email first.
    4. No account: a new passwordless, verified user is created.
    """
    account = db.scalar(
        select(AuthAccount).where(
            AuthAccount.provider == provider,
            AuthAccount.provider_account_id == provider_id,
        )
    )
    github_id = int(provider_id) if provider == "github" and provider_id.isdigit() else None
    if account:
        user = db.get(User, account.user_id)
        if user:
            if login is not None and account.provider_login != login:
                account.provider_login = login
                db.commit()
            provision_domain_user_and_org(db, user, github_user_id=github_id)
            return user
    if not email_verified:
        raise OAuthError("email_unverified", public="oauth_email_unverified")
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and not user.email_verified:
        raise OAuthError("link_refused_local_unverified", public="oauth_link_refused")
    if user is None:
        user = User(name=name[:120] or email.split("@")[0], email=email, email_verified=True)
        db.add(user)
        db.flush()
    db.add(
        AuthAccount(
            user_id=user.id,
            provider=provider,
            provider_account_id=provider_id,
            provider_login=login,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise OAuthError("account_conflict") from exc
    db.refresh(user)
    provision_domain_user_and_org(db, user, github_user_id=github_id)
    return user
