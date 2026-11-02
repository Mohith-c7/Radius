"""Verdict v2 persistence models (VS-07; design VERDICT_V2_SLICE.md 4.2).

``verdict_v2`` holds one row per computation: the whole computed bundle as
JSON plus the columns needed for list/summary queries without parsing it.
``verdict_v2_requests`` is the outbox: one row per analysis that needs a
recompute and republish (CI results arrived, or a bundle was recomputed).

Every table carries ``organization_id`` (tenant isolation); the repository in
``radius_shared.verdict_v2_repository`` filters every query by it. Enum-like
columns are plain strings so adding a state needs no migration.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from radius_shared.database.base import Base, UuidPrimaryKeyMixin


class VerdictV2Row(UuidPrimaryKeyMixin, Base):
    """One computed verdict v2 bundle for an analysis (idempotent on its inputs digest)."""

    __tablename__ = "verdict_v2"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"), nullable=False
    )
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    algo_version: Mapped[str] = mapped_column(String(48), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    config_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    criteria_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    criteria_proven: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    criteria_weak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    criteria_unevidenced: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    criteria_contradicted: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    criteria_excluded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uim: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    bundle: Mapped[dict] = mapped_column(JSON, nullable=False)
    justification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback: Mapped[str | None] = mapped_column(String(8), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "revision", name="uq_verdict_v2_analysis_revision"
        ),
        UniqueConstraint(
            "analysis_id", "inputs_digest", name="uq_verdict_v2_analysis_inputs_digest"
        ),
        Index("ix_verdict_v2_organization_id", "organization_id"),
        Index("ix_verdict_v2_analysis_id", "analysis_id"),
    )


class VerdictV2RequestRow(UuidPrimaryKeyMixin, Base):
    """Outbox row: this analysis needs a Stage B recompute and a republish."""

    __tablename__ = "verdict_v2_requests"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_verdict_v2_requests_analysis_id"),
        Index("ix_verdict_v2_requests_organization_id", "organization_id"),
        Index("ix_verdict_v2_requests_available_at", "available_at"),
    )
