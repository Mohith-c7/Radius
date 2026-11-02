"""Create intent persistence tables (sources, snapshots, criteria, audit).

Revision ID: 20261102_0011
Revises: 20261102_0010
Create Date: 2026-11-02

IN-07. Models live in ``radius_shared.database.intent``. Every table carries
``organization_id``; the repository filters by it on every query.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0011"
down_revision: str | None = "20261102_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intent_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("raw_text_hash", sa.String(length=64), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("suspicious_content_removed", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "kind",
            "source_ref",
            "raw_text_hash",
            name="uq_intent_sources_analysis_kind_ref_hash",
        ),
    )
    op.create_index(
        "ix_intent_sources_organization_id", "intent_sources", ["organization_id"]
    )
    op.create_index("ix_intent_sources_analysis_id", "intent_sources", ["analysis_id"])

    op.create_table(
        "intent_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["parent_snapshot_id"], ["intent_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "version", name="uq_intent_snapshots_analysis_version"
        ),
        sa.UniqueConstraint(
            "analysis_id",
            "content_hash",
            name="uq_intent_snapshots_analysis_content_hash",
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_intent_snapshots_version_positive")),
    )
    op.create_index(
        "ix_intent_snapshots_organization_id", "intent_snapshots", ["organization_id"]
    )
    op.create_index("ix_intent_snapshots_analysis_id", "intent_snapshots", ["analysis_id"])
    op.create_index(
        "ix_intent_snapshots_parent_snapshot_id",
        "intent_snapshots",
        ["parent_snapshot_id"],
    )

    op.create_table(
        "intent_snapshot_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_row_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["intent_snapshots.id"]),
        sa.ForeignKeyConstraint(["source_row_id"], ["intent_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "source_row_id", name="uq_intent_snapshot_sources_pair"
        ),
    )
    op.create_index(
        "ix_intent_snapshot_sources_organization_id",
        "intent_snapshot_sources",
        ["organization_id"],
    )
    op.create_index(
        "ix_intent_snapshot_sources_snapshot_id",
        "intent_snapshot_sources",
        ["snapshot_id"],
    )
    op.create_index(
        "ix_intent_snapshot_sources_source_row_id",
        "intent_snapshot_sources",
        ["source_row_id"],
    )

    op.create_table(
        "intent_criteria",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("source_row_id", sa.Uuid(), nullable=False),
        sa.Column("origin_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extraction_method", sa.String(length=32), nullable=False),
        sa.Column("extractor_version", sa.String(length=64), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("testability", sa.String(length=32), nullable=False),
        sa.Column("testability_rationale", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("hints", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["intent_snapshots.id"]),
        sa.ForeignKeyConstraint(["source_row_id"], ["intent_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "criterion_id", name="uq_intent_criteria_snapshot_criterion"
        ),
        sa.UniqueConstraint(
            "snapshot_id", "position", name="uq_intent_criteria_snapshot_position"
        ),
        sa.CheckConstraint(
            "span_start >= 0 AND span_end > span_start",
            name=op.f("ck_intent_criteria_span_valid"),
        ),
        sa.CheckConstraint(
            "weight > 0 AND weight <= 1", name=op.f("ck_intent_criteria_weight_range")
        ),
    )
    op.create_index(
        "ix_intent_criteria_organization_id", "intent_criteria", ["organization_id"]
    )
    op.create_index("ix_intent_criteria_snapshot_id", "intent_criteria", ["snapshot_id"])
    op.create_index(
        "ix_intent_criteria_source_row_id", "intent_criteria", ["source_row_id"]
    )

    op.create_table(
        "intent_criterion_state_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("old_state", sa.String(length=32), nullable=False),
        sa.Column("new_state", sa.String(length=32), nullable=False),
        sa.Column("old_text", sa.Text(), nullable=True),
        sa.Column("new_text", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "criterion_id"],
            ["intent_criteria.snapshot_id", "intent_criteria.criterion_id"],
            name="fk_intent_state_changes_criterion",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "criterion_id",
            "sequence",
            name="uq_intent_state_changes_criterion_sequence",
        ),
    )
    op.create_index(
        "ix_intent_state_changes_organization_id",
        "intent_criterion_state_changes",
        ["organization_id"],
    )
    op.create_index(
        "ix_intent_state_changes_snapshot_criterion",
        "intent_criterion_state_changes",
        ["snapshot_id", "criterion_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intent_state_changes_snapshot_criterion",
        table_name="intent_criterion_state_changes",
    )
    op.drop_index(
        "ix_intent_state_changes_organization_id",
        table_name="intent_criterion_state_changes",
    )
    op.drop_table("intent_criterion_state_changes")
    op.drop_index("ix_intent_criteria_source_row_id", table_name="intent_criteria")
    op.drop_index("ix_intent_criteria_snapshot_id", table_name="intent_criteria")
    op.drop_index("ix_intent_criteria_organization_id", table_name="intent_criteria")
    op.drop_table("intent_criteria")
    op.drop_index(
        "ix_intent_snapshot_sources_source_row_id",
        table_name="intent_snapshot_sources",
    )
    op.drop_index(
        "ix_intent_snapshot_sources_snapshot_id", table_name="intent_snapshot_sources"
    )
    op.drop_index(
        "ix_intent_snapshot_sources_organization_id",
        table_name="intent_snapshot_sources",
    )
    op.drop_table("intent_snapshot_sources")
    op.drop_index(
        "ix_intent_snapshots_parent_snapshot_id", table_name="intent_snapshots"
    )
    op.drop_index("ix_intent_snapshots_analysis_id", table_name="intent_snapshots")
    op.drop_index("ix_intent_snapshots_organization_id", table_name="intent_snapshots")
    op.drop_table("intent_snapshots")
    op.drop_index("ix_intent_sources_analysis_id", table_name="intent_sources")
    op.drop_index("ix_intent_sources_organization_id", table_name="intent_sources")
    op.drop_table("intent_sources")
