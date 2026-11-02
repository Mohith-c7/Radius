"""SQLAlchemy persistence models for the intent layer (IN-07).

Every table carries ``organization_id`` (tenant isolation); repositories filter
by it on every query. Enum-like columns are plain strings validated by the
``radius_intent`` domain, so adding a kind or state needs no migration.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radius_shared.database.base import Base, UuidPrimaryKeyMixin


class IntentSourceRow(UuidPrimaryKeyMixin, Base):
    """One raw intent text as fetched for an analysis (one row per content hash)."""

    __tablename__ = "intent_sources"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suspicious_content_removed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "kind",
            "source_ref",
            "raw_text_hash",
            name="uq_intent_sources_analysis_kind_ref_hash",
        ),
        Index("ix_intent_sources_organization_id", "organization_id"),
        Index("ix_intent_sources_analysis_id", "analysis_id"),
    )


class IntentSnapshotRow(UuidPrimaryKeyMixin, Base):
    """Immutable versioned set of criteria for one analysis."""

    __tablename__ = "intent_snapshots"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("intent_snapshots.id"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    source_links: Mapped[list["IntentSnapshotSourceRow"]] = relationship(
        order_by="IntentSnapshotSourceRow.position"
    )
    criteria: Mapped[list["IntentCriterionRow"]] = relationship(
        order_by="IntentCriterionRow.position"
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "version", name="uq_intent_snapshots_analysis_version"
        ),
        UniqueConstraint(
            "analysis_id",
            "content_hash",
            name="uq_intent_snapshots_analysis_content_hash",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_intent_snapshots_organization_id", "organization_id"),
        Index("ix_intent_snapshots_analysis_id", "analysis_id"),
        Index("ix_intent_snapshots_parent_snapshot_id", "parent_snapshot_id"),
    )


class IntentSnapshotSourceRow(UuidPrimaryKeyMixin, Base):
    """Association: which source rows a snapshot was built from, in order."""

    __tablename__ = "intent_snapshot_sources"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent_snapshots.id"), nullable=False
    )
    source_row_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent_sources.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[IntentSourceRow] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "source_row_id", name="uq_intent_snapshot_sources_pair"
        ),
        Index("ix_intent_snapshot_sources_organization_id", "organization_id"),
        Index("ix_intent_snapshot_sources_snapshot_id", "snapshot_id"),
        Index("ix_intent_snapshot_sources_source_row_id", "source_row_id"),
    )


class IntentCriterionRow(UuidPrimaryKeyMixin, Base):
    """One criterion inside a snapshot; only state and wording ever change."""

    __tablename__ = "intent_criteria"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent_snapshots.id"), nullable=False
    )
    criterion_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_row_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent_sources.id"), nullable=False
    )
    origin_retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    testability: Mapped[str] = mapped_column(String(32), nullable=False)
    testability_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    hints: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    source: Mapped[IntentSourceRow] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "criterion_id", name="uq_intent_criteria_snapshot_criterion"
        ),
        UniqueConstraint(
            "snapshot_id", "position", name="uq_intent_criteria_snapshot_position"
        ),
        CheckConstraint("span_start >= 0 AND span_end > span_start", name="span_valid"),
        CheckConstraint("weight > 0 AND weight <= 1", name="weight_range"),
        Index("ix_intent_criteria_organization_id", "organization_id"),
        Index("ix_intent_criteria_snapshot_id", "snapshot_id"),
        Index("ix_intent_criteria_source_row_id", "source_row_id"),
    )


class IntentCriterionStateChangeRow(UuidPrimaryKeyMixin, Base):
    """Append-only audit of confirm/reject/edit/reopen transitions."""

    __tablename__ = "intent_criterion_state_changes"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    old_state: Mapped[str] = mapped_column(String(32), nullable=False)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    old_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "criterion_id",
            "sequence",
            name="uq_intent_state_changes_criterion_sequence",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "criterion_id"],
            ["intent_criteria.snapshot_id", "intent_criteria.criterion_id"],
            name="fk_intent_state_changes_criterion",
        ),
        Index("ix_intent_state_changes_organization_id", "organization_id"),
        Index(
            "ix_intent_state_changes_snapshot_criterion",
            "snapshot_id",
            "criterion_id",
        ),
    )
