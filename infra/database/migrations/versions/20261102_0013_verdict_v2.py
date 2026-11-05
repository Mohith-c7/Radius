"""Create the verdict_v2 table (bundle store of Verdict v2 alpha).

Revision ID: 20261102_0013
Revises: 20261102_0012
Create Date: 2026-11-02

Models live in ``radius_shared.database.verdict_v2``. The table carries
``organization_id``; the repository filters by it on every query.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0013"
down_revision: str | None = "20261102_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verdict_v2",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("inputs_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=True),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=True),
        sa.Column("algo_version", sa.String(length=48), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("config_digest", sa.String(length=80), nullable=False),
        sa.Column("criteria_total", sa.Integer(), nullable=False),
        sa.Column("criteria_proven", sa.Integer(), nullable=False),
        sa.Column("criteria_weak", sa.Integer(), nullable=False),
        sa.Column("criteria_unevidenced", sa.Integer(), nullable=False),
        sa.Column("criteria_contradicted", sa.Integer(), nullable=False),
        sa.Column("criteria_excluded", sa.Integer(), nullable=False),
        sa.Column("uim", sa.Float(), nullable=True),
        sa.Column("intent_coverage", sa.Float(), nullable=True),
        sa.Column("bundle", sa.JSON(), nullable=False),
        sa.Column("justification", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("fallback", sa.String(length=8), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_digest", sa.String(length=64), nullable=True),
        sa.Column("publish_error", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "revision", name="uq_verdict_v2_analysis_revision"
        ),
        sa.UniqueConstraint(
            "analysis_id", "inputs_digest", name="uq_verdict_v2_analysis_inputs_digest"
        ),
    )
    op.create_index("ix_verdict_v2_organization_id", "verdict_v2", ["organization_id"])
    op.create_index("ix_verdict_v2_analysis_id", "verdict_v2", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_verdict_v2_analysis_id", table_name="verdict_v2")
    op.drop_index("ix_verdict_v2_organization_id", table_name="verdict_v2")
    op.drop_table("verdict_v2")
