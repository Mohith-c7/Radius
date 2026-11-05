"""Create mutation_result_cache (final mutant results, per repository).

Revision ID: 20261103_0016
Revises: 20261102_0015
Create Date: 2026-11-03

Model: ``radius_shared.database.verdict_v2.MutationResultCacheRow``. Stores only final
``killed`` / ``survived`` results keyed by a content hash, namespaced by organization and
repository. The revision number may be renumbered at merge time if another migration
lands first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0016"
down_revision: str | None = "20261102_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mutation_result_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("killed_by", sa.JSON(), nullable=False),
        sa.Column("algo_version", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "repository_id",
            "cache_key",
            name="uq_mutation_result_cache_key",
        ),
    )
    op.create_index(
        "ix_mutation_result_cache_created_at",
        "mutation_result_cache",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mutation_result_cache_created_at", table_name="mutation_result_cache"
    )
    op.drop_table("mutation_result_cache")
