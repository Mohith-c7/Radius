"""Authentication services: password hashing, signed sessions, and opaque action tokens."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuthAccount, AuthSession, AuthToken, User

password_hasher = PasswordHasher()
SESSION_TTL = timedelta(days=14)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_session(db: Session, user: User, remember: bool = False) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + (timedelta(days=30) if remember else SESSION_TTL)
    session = AuthSession(user_id=user.id, expires_at=expires.replace(tzinfo=None))
    db.add(session)
    db.commit()
    return jwt.encode({"sub": user.id, "sid": session.id, "exp": expires, "type": "session"}, settings.session_secret, algorithm="HS256")


def decode_session(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
        if payload.get("type") != "session":
            raise jwt.InvalidTokenError
        return str(payload["sub"]), str(payload["sid"])
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.") from error


def create_action_token(db: Session, user_id: str, purpose: str, minutes: int = 60) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user_id, purpose=purpose, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), expires_at=datetime.utcnow() + timedelta(minutes=minutes)))
    db.commit()
    return raw_token


def consume_action_token(db: Session, raw_token: str, purpose: str) -> User:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == token_hash, AuthToken.purpose == purpose))
    if token is None or token.used_at is not None or token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This link is invalid or has expired.")
    token.used_at = datetime.utcnow()
    user = db.get(User, token.user_id)
    db.commit()
    if user is None:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired.")
    return user


def user_from_provider(db: Session, provider: str, provider_id: str, email: str, name: str) -> User:
    account = db.scalar(select(AuthAccount).where(AuthAccount.provider == provider, AuthAccount.provider_account_id == provider_id))
    if account:
        return db.get(User, account.user_id)
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        user = User(name=name[:120] or email.split("@")[0], email=email.lower(), email_verified=True)
        db.add(user)
        db.flush()
    db.add(AuthAccount(user_id=user.id, provider=provider, provider_account_id=provider_id))
    db.commit()
    db.refresh(user)
    return user
