"""phase 1 artifact persistence

Revision ID: 20260729_0002
Revises: 20260729_0001
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260729_0002"
down_revision: str | None = "20260729_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "confidence_reports",
        sa.Column("recommendations", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "analysis_jobs",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="analysisjobstatus",
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_analysis_jobs_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_jobs")),
        sa.UniqueConstraint("analysis_id", name=op.f("uq_analysis_jobs_analysis_id")),
    )
    op.create_index(
        "ix_analysis_jobs_analysis_id",
        "analysis_jobs",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_jobs_status_created_at",
        "analysis_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "graph_nodes",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("node_key", sa.Text(), nullable=False),
        sa.Column("node_type", sa.String(length=100), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["graph_snapshots.id"],
            name=op.f("fk_graph_nodes_snapshot_id_graph_snapshots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint(
            "snapshot_id",
            "node_key",
            name="uq_graph_nodes_snapshot_key",
        ),
    )
    op.create_index("ix_graph_nodes_snapshot_id", "graph_nodes", ["snapshot_id"])
    op.create_table(
        "graph_edges",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.String(length=100), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["graph_snapshots.id"],
            name=op.f("fk_graph_edges_snapshot_id_graph_snapshots"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_key",
            "target_key",
            "edge_type",
            name="uq_graph_edges_snapshot_edge",
        ),
    )
    op.create_index("ix_graph_edges_snapshot_id", "graph_edges", ["snapshot_id"])
    op.create_table(
        "test_cases",
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("framework", sa.String(length=100), nullable=False),
        sa.Column("test_type", sa.String(length=100), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("test_metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
        sa.UniqueConstraint("path", name=op.f("uq_test_cases_path")),
    )
    op.create_index("ix_test_cases_path", "test_cases", ["path"], unique=False)
    op.create_table(
        "test_selections",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_test_selections_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_selections")),
        sa.UniqueConstraint(
            "analysis_id",
            name=op.f("uq_test_selections_analysis_id"),
        ),
    )
    op.create_index(
        "ix_test_selections_analysis_id",
        "test_selections",
        ["analysis_id"],
    )
    op.create_table(
        "selected_tests",
        sa.Column("selection_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["test_selections.id"],
            name=op.f("fk_selected_tests_selection_id_test_selections"),
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_selected_tests_test_case_id_test_cases"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_selected_tests")),
        sa.UniqueConstraint(
            "selection_id",
            "test_case_id",
            name="uq_selected_tests_selection_case",
        ),
    )
    op.create_index(
        "ix_selected_tests_selection_id",
        "selected_tests",
        ["selection_id"],
    )
    op.create_table(
        "test_run_plans",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("selected_test_paths", sa.JSON(), nullable=False),
        sa.Column("command_plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_test_run_plans_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_run_plans")),
        sa.UniqueConstraint(
            "analysis_id",
            name=op.f("uq_test_run_plans_analysis_id"),
        ),
    )
    op.create_index(
        "ix_test_run_plans_analysis_id",
        "test_run_plans",
        ["analysis_id"],
    )
    op.create_table(
        "confidence_evidence",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("impact", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Numeric(10, 2), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["confidence_reports.id"],
            name=op.f("fk_confidence_evidence_report_id_confidence_reports"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confidence_evidence")),
    )
    op.create_index(
        "ix_confidence_evidence_report_id",
        "confidence_evidence",
        ["report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_confidence_evidence_report_id", table_name="confidence_evidence")
    op.drop_table("confidence_evidence")
    op.drop_index("ix_test_run_plans_analysis_id", table_name="test_run_plans")
    op.drop_table("test_run_plans")
    op.drop_index("ix_selected_tests_selection_id", table_name="selected_tests")
    op.drop_table("selected_tests")
    op.drop_index("ix_test_selections_analysis_id", table_name="test_selections")
    op.drop_table("test_selections")
    op.drop_index("ix_test_cases_path", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index("ix_graph_edges_snapshot_id", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_snapshot_id", table_name="graph_nodes")
    op.drop_table("graph_nodes")
    op.drop_index("ix_analysis_jobs_status_created_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_analysis_id", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_column("confidence_reports", "recommendations")
    sa.Enum(name="analysisjobstatus").drop(op.get_bind(), checkfirst=True)
