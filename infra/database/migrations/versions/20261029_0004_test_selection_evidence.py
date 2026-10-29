"""add evidence-backed test-selection decisions

Revision ID: 20261029_0004
Revises: 20260729_0003, 20261029_0003_test_history
"""

from alembic import op
import sqlalchemy as sa

revision = "20261029_0004"
down_revision = ("20260729_0003", "20261029_0003_test_history")
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
    op.create_unique_constraint("uq_test_execution_history_analysis_test", "test_execution_histories", ["analysis_id", "test_path"])


def downgrade() -> None:
    op.drop_constraint("uq_test_execution_history_analysis_test", "test_execution_histories", type_="unique")
    op.drop_index("ix_test_selection_evidence_selection_id", table_name="test_selection_evidence")
    op.drop_table("test_selection_evidence")
