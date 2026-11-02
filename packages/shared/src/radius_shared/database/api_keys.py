"""Managed API key tables (PRD-12): hashed keys plus an append-only audit trail."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from radius_shared.database.base import Base, UuidPrimaryKeyMixin


class ApiKey(UuidPrimaryKeyMixin, Base):
    """One managed API key. Only a keyed fingerprint of the secret is stored."""

    __tablename__ = "api_keys"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Public, non-secret identifier embedded in the token (``rdk_<prefix>_...``).
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Hex HMAC-SHA256 fingerprint of the full token; never the token itself.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rotated_from_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_keys.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "prefix", name="uq_api_keys_org_prefix"),
        Index("ix_api_keys_organization_id", "organization_id"),
    )


class ApiKeyAuditEvent(UuidPrimaryKeyMixin, Base):
    """Who created, rotated or revoked which key. Never holds secret material."""

    __tablename__ = "api_key_audit_events"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    api_key_id: Mapped[UUID] = mapped_column(ForeignKey("api_keys.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_api_key_audit_events_organization_id", "organization_id"),
    )
