"""Add analysis_ai_reviews (advisory AI merge-readiness review, DEC-041).

Revision ID: 20261120_0025
Revises: 20261119_0022
Create Date: 2026-11-20

One row per analysis: the validated AI review JSON, or the reason it is unavailable. Read
only by GET /analyses/{id}/ai-review, the dashboard panel and the PR comment section; never
by verdict, score or check-run logic.

Merge note: this branch was cut when 20261119_0022 was the head. Another branch adds
0023 and 0024; whichever lands second must set ``down_revision`` to the other head (this
revision id was chosen so it does not collide with 0023/0024). Idempotent: the table is
created only when absent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_0025"
down_revision: str | None = "20261119_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "analysis_ai_reviews"


def _exists() -> bool:
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _exists():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("review", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", name="uq_analysis_ai_reviews_analysis_id"),
    )
    op.create_index(
        "ix_analysis_ai_reviews_organization_id", TABLE, ["organization_id"]
    )


def downgrade() -> None:
    if not _exists():
        return
    op.drop_index("ix_analysis_ai_reviews_organization_id", table_name=TABLE)
    op.drop_table(TABLE)
