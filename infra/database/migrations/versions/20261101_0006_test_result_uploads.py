"""Accumulate CI test result uploads per analysis

Before this revision each upload overwrote the single ``test_runs`` row of an
analysis, so a later all-passing upload (another CI shard or a replay) could
erase an earlier failure. Every distinct upload is now stored with the commit
it is bound to, its body hash (exact replays are idempotent) and the executed
test-case identities, so the verdict can be recomputed over all uploads.

Revision ID: 20261101_0006
Revises: 20261101_0005
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0006"
down_revision: str | None = "20261101_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_result_uploads",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_tests", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_test_result_uploads_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_result_uploads")),
        sa.UniqueConstraint(
            "analysis_id",
            "body_sha256",
            name="uq_test_result_uploads_analysis_id_body_sha256",
        ),
    )
    op.create_index(
        "ix_test_result_uploads_analysis_id",
        "test_result_uploads",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_test_result_uploads_analysis_id",
        table_name="test_result_uploads",
    )
    op.drop_table("test_result_uploads")
