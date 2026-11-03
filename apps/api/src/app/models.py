"""Persistent authentication models. Provider accounts enable safe account linking."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "auth_users"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(32), default="developer")
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )
    accounts: Mapped[list["AuthAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthAccount(Base):
    __tablename__ = "auth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_provider_account"),
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    user: Mapped[User] = relationship(back_populates="accounts")


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class AuthOAuthFlow(Base):
    """One in-flight OAuth/OIDC sign-in. Single use: the row is deleted when the callback consumes it.

    Only SHA-256 hashes of the browser flow id (cookie) and of ``state`` are stored. The PKCE
    verifier and the OIDC nonce are needed again at the callback, so they are stored in the
    clear for at most ten minutes (they are useless without the one-time authorization code).
    """

    __tablename__ = "auth_oauth_flows"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    flow_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(24))
    nonce: Mapped[str] = mapped_column(String(128))
    code_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(512), default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
