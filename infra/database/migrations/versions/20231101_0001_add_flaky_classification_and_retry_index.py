"""Alembic migration to add flaky classification table and retry_index column.

Revision ID: 20231101_0001  (was: add_flaky_classification_and_retry_index — too long for alembic_version VARCHAR(32))
Revises: 20261029_0005_runtime_coverage
Create Date: 2023-11-01 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20231101_0001"
down_revision = "20261029_0005"
branch_labels = None
depends_on = None



def upgrade() -> None:
    # Explicitly create the enum type (idempotent via DO block) so this
    # migration is safe after a partial failure or when re-running in tests.
    # NOTE: CREATE TYPE IF NOT EXISTS requires PostgreSQL 17+; use DO block.
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'flakystatus') THEN
                CREATE TYPE flakystatus AS ENUM
                    ('stable', 'potentially_flaky', 'failing', 'insufficient_data');
            END IF;
        END $$;
        """
    )
    # Add retry_index to test_runs table
    op.add_column(
        "test_runs",
        sa.Column("retry_index", sa.Integer(), nullable=False, server_default="0"),
    )
    # Create flaky_classification table (create_type=False: type already created above)
    op.create_table(
        "flaky_classification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "stable",
                "potentially_flaky",
                "failing",
                "insufficient_data",
                name="flakystatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_id", name="uq_flaky_classification_test_case"),
        sa.Index("ix_flaky_classification_status", "status"),
    )



def downgrade() -> None:
    op.drop_table("flaky_classification")
    op.drop_column("test_runs", "retry_index")
    # Drop the PostgreSQL enum type that was created with the table.
    op.execute("DROP TYPE IF EXISTS flakystatus")
