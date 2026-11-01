"""Create runtime coverage tables (coverage reports, test associations, artifacts).

Revision ID: 20261101_0009
Revises: 20261101_0008
Create Date: 2026-11-01

The coverage models (radius_shared.database.coverage) shipped without a
migration, so the SQL coverage store had no tables to write to.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0009"
down_revision: str | None = "20261101_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "coverage_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("framework", sa.String(length=100), nullable=False),
        sa.Column("covered_lines", sa.Integer(), nullable=False),
        sa.Column("total_lines", sa.Integer(), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # One coverage report per analysis (model: unique=True, index=True).
    op.create_index(
        "ix_coverage_reports_analysis_id", "coverage_reports", ["analysis_id"], unique=True
    )
    op.create_table(
        "coverage_report_test_association",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["report_id"], ["coverage_reports.id"]),
        sa.ForeignKeyConstraint(["test_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "test_id", name="uq_coverage_report_test"),
    )
    op.create_index(
        "ix_coverage_report_test_association_report_id",
        "coverage_report_test_association",
        ["report_id"],
    )
    op.create_index(
        "ix_coverage_report_test_association_test_id",
        "coverage_report_test_association",
        ["test_id"],
    )
    op.create_table(
        "coverage_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("symbol", sa.String(length=1024), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("covered", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["report_id"], ["coverage_reports.id"]),
        sa.ForeignKeyConstraint(["test_id"], ["coverage_report_test_association.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_id", "path", "symbol", name="uq_coverage_lines"),
    )
    for column in ("report_id", "test_id", "path", "symbol"):
        op.create_index(f"ix_coverage_artifacts_{column}", "coverage_artifacts", [column])


def downgrade() -> None:
    for column in ("report_id", "test_id", "path", "symbol"):
        op.drop_index(f"ix_coverage_artifacts_{column}", table_name="coverage_artifacts")
    op.drop_table("coverage_artifacts")
    op.drop_index(
        "ix_coverage_report_test_association_test_id",
        table_name="coverage_report_test_association",
    )
    op.drop_index(
        "ix_coverage_report_test_association_report_id",
        table_name="coverage_report_test_association",
    )
    op.drop_table("coverage_report_test_association")
    op.drop_index("ix_coverage_reports_analysis_id", table_name="coverage_reports")
    op.drop_table("coverage_reports")
