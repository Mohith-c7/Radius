"""Phase 3 decoupled confidence metrics

Revision ID: 20261002_0004
Revises: 20260729_0003
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0004"
down_revision: str | None = "20260729_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "confidence_reports",
        sa.Column("change_risk", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "confidence_reports",
        sa.Column("verification_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "confidence_reports",
        sa.Column("analysis_completeness", sa.Numeric(precision=5, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("confidence_reports", "analysis_completeness")
    op.drop_column("confidence_reports", "verification_status")
    op.drop_column("confidence_reports", "change_risk")
