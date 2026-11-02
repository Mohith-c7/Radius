"""Create the verdict_v2_requests outbox (republish after CI).

Revision ID: 20261102_0014
Revises: 20261102_0013
Create Date: 2026-11-02

Models live in ``radius_shared.database.verdict_v2``. One row per analysis
(``UNIQUE(analysis_id)``); the API upserts, the worker claims, recomputes,
publishes and deletes the row only when ``requested_at`` is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0014"
down_revision: str | None = "20261102_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verdict_v2_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="uq_verdict_v2_requests_analysis_id"),
    )
    op.create_index(
        "ix_verdict_v2_requests_organization_id",
        "verdict_v2_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_verdict_v2_requests_available_at",
        "verdict_v2_requests",
        ["available_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verdict_v2_requests_available_at", table_name="verdict_v2_requests"
    )
    op.drop_index(
        "ix_verdict_v2_requests_organization_id", table_name="verdict_v2_requests"
    )
    op.drop_table("verdict_v2_requests")
