"""initial phase 1 schema

Revision ID: 20260729_0001
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("github_installation_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint(
            "github_installation_id",
            name=op.f("uq_organizations_github_installation_id"),
        ),
    )
    op.create_table(
        "repositories",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("github", name="repositoryprovider"),
            nullable=False,
        ),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("clone_url", sa.Text(), nullable=False),
        sa.Column(
            "visibility",
            sa.Enum("public", "private", "internal", name="repositoryvisibility"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "connected",
                "synchronizing",
                "failed",
                "disconnected",
                name="repositorystatus",
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_repositories_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint(
            "github_repository_id",
            name=op.f("uq_repositories_github_repository_id"),
        ),
    )
    op.create_index(
        "ix_repositories_github_repository_id",
        "repositories",
        ["github_repository_id"],
        unique=False,
    )
    op.create_index(
        "ix_repositories_organization_id",
        "repositories",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.Enum("admin", "developer", name="userrole"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_users_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("github_user_id", name=op.f("uq_users_github_user_id")),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_table(
        "branches",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("latest_commit_sha", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_branches_repository_id_repositories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("repository_id", "name", name="uq_branches_repository_name"),
    )
    op.create_index("ix_branches_repository_id", "branches", ["repository_id"])
    op.create_table(
        "pull_requests",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("github_pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_branch", sa.String(length=255), nullable=False),
        sa.Column("target_branch", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "closed", "merged", name="pullrequeststatus"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_pull_requests_repository_id_repositories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pull_requests")),
        sa.UniqueConstraint(
            "repository_id",
            "github_pr_number",
            name="uq_pull_requests_repository_pr_number",
        ),
    )
    op.create_index(
        "ix_pull_requests_repository_id_github_pr_number",
        "pull_requests",
        ["repository_id", "github_pr_number"],
    )
    op.create_table(
        "analyses",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="analysisstatus",
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["pull_requests.id"],
            name=op.f("fk_analyses_pull_request_id_pull_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_analyses_repository_id_repositories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
    )
    op.create_index("ix_analyses_commit_sha", "analyses", ["commit_sha"])
    op.create_index("ix_analyses_pull_request_id", "analyses", ["pull_request_id"])
    op.create_index("ix_analyses_repository_id", "analyses", ["repository_id"])
    op.create_table(
        "blast_radius",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("affected_files", sa.Integer(), nullable=False),
        sa.Column("affected_symbols", sa.Integer(), nullable=False),
        sa.Column("affected_modules", sa.Integer(), nullable=False),
        sa.Column("affected_tests", sa.Integer(), nullable=False),
        sa.Column("dependency_depth", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_blast_radius_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blast_radius")),
        sa.UniqueConstraint("analysis_id", name=op.f("uq_blast_radius_analysis_id")),
    )
    op.create_table(
        "changed_files",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "change_type",
            sa.Enum("added", "modified", "deleted", "renamed", name="changedfiletype"),
            nullable=False,
        ),
        sa.Column("additions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_changed_files_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changed_files")),
    )
    op.create_index("ix_changed_files_analysis_id", "changed_files", ["analysis_id"])
    op.create_table(
        "confidence_reports",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum("low", "medium", "high", "critical", name="risklevel"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_confidence_reports_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confidence_reports")),
        sa.UniqueConstraint(
            "analysis_id",
            name=op.f("uq_confidence_reports_analysis_id"),
        ),
    )
    op.create_index(
        "ix_confidence_reports_analysis_id",
        "confidence_reports",
        ["analysis_id"],
    )
    op.create_table(
        "graph_snapshots",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("graph_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_graph_snapshots_analysis_id_analyses"),
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_graph_snapshots_repository_id_repositories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_snapshots")),
        sa.UniqueConstraint(
            "analysis_id",
            name=op.f("uq_graph_snapshots_analysis_id"),
        ),
    )
    op.create_table(
        "test_runs",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("framework", sa.String(length=100), nullable=False),
        sa.Column("total_tests", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_test_runs_analysis_id_analyses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_runs")),
    )
    op.create_index("ix_test_runs_analysis_id", "test_runs", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_test_runs_analysis_id", table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_table("graph_snapshots")
    op.drop_index(
        "ix_confidence_reports_analysis_id",
        table_name="confidence_reports",
    )
    op.drop_table("confidence_reports")
    op.drop_index("ix_changed_files_analysis_id", table_name="changed_files")
    op.drop_table("changed_files")
    op.drop_table("blast_radius")
    op.drop_index("ix_analyses_repository_id", table_name="analyses")
    op.drop_index("ix_analyses_pull_request_id", table_name="analyses")
    op.drop_index("ix_analyses_commit_sha", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index(
        "ix_pull_requests_repository_id_github_pr_number",
        table_name="pull_requests",
    )
    op.drop_table("pull_requests")
    op.drop_index("ix_branches_repository_id", table_name="branches")
    op.drop_table("branches")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_repositories_organization_id", table_name="repositories")
    op.drop_index("ix_repositories_github_repository_id", table_name="repositories")
    op.drop_table("repositories")
    op.drop_table("organizations")
    sa.Enum(name="risklevel").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="changedfiletype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="analysisstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="pullrequeststatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="repositorystatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="repositoryvisibility").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="repositoryprovider").drop(op.get_bind(), checkfirst=True)
