"""test execution history

Revision ID: 20261101_0007
Revises: 20261101_0006
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0007"
down_revision: str | None = "20261101_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_execution_histories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_name", sa.String(length=255), nullable=False),
        sa.Column("test_path", sa.String(length=500), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("pr_id", sa.Integer(), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_info", sa.Text(), nullable=True),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("framework", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_execution_histories")),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_test_execution_histories_repository_id_repositories",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name="fk_test_execution_histories_analysis_id_analyses",
        ),
    )
    op.create_index(
        "ix_test_execution_histories_analysis_id",
        "test_execution_histories",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_execution_histories_test_path",
        "test_execution_histories",
        ["test_path"],
        unique=False,
    )
    op.create_index(
        "ix_test_execution_histories_repository_id",
        "test_execution_histories",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_execution_histories_status_timestamp",
        "test_execution_histories",
        ["status", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_test_execution_histories_timestamp",
        "test_execution_histories",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_test_execution_histories_timestamp",
        table_name="test_execution_histories",
    )
    op.drop_index(
        "ix_test_execution_histories_status_timestamp",
        table_name="test_execution_histories",
    )
    op.drop_index(
        "ix_test_execution_histories_repository_id",
        table_name="test_execution_histories",
    )
    op.drop_index(
        "ix_test_execution_histories_test_path",
        table_name="test_execution_histories",
    )
    op.drop_index(
        "ix_test_execution_histories_analysis_id",
        table_name="test_execution_histories",
    )
    op.drop_table("test_execution_histories")
