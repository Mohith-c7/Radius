"""add evidence-backed test-selection decisions

Revision ID: 20261101_0008
Revises: 20261101_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20261101_0008"
down_revision = "20261101_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_selection_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("evidence_sources", sa.JSON(), nullable=False),
        sa.Column("evidence_details", sa.JSON(), nullable=False),
        sa.Column("relevance_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["selection_id"], ["test_selections.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("selection_id", "test_case_id", name="uq_test_selection_evidence_case"),
    )
    op.create_index("ix_test_selection_evidence_selection_id", "test_selection_evidence", ["selection_id"])
    # batch mode: SQLite cannot ALTER constraints in place (no-op wrapper on PostgreSQL).
    with op.batch_alter_table("test_execution_histories") as batch:
        batch.create_unique_constraint(
            "uq_test_execution_history_analysis_test", ["analysis_id", "test_path"]
        )


def downgrade() -> None:
    with op.batch_alter_table("test_execution_histories") as batch:
        batch.drop_constraint("uq_test_execution_history_analysis_test", type_="unique")
    op.drop_index("ix_test_selection_evidence_selection_id", table_name="test_selection_evidence")
    op.drop_table("test_selection_evidence")
