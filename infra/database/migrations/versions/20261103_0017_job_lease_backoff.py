"""Add analysis_jobs.claimed_by and analysis_jobs.available_at (lease owner, retry backoff).

Revision ID: 20261103_0017
Revises: 20261103_0016
Create Date: 2026-11-03

C-02: ``claimed_by`` is the worker that holds the lease; heartbeat, completion, failure and
requeue only apply while it still matches. C-05: ``available_at`` is the earliest time a
requeued job may be claimed again (exponential backoff). Both are nullable, so existing rows
and older workers keep working. The revision number may be renumbered at merge time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0017"
down_revision: str | None = "20261103_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("analysis_jobs")}


def upgrade() -> None:
    existing = _columns()
    if "claimed_by" not in existing:
        op.add_column("analysis_jobs", sa.Column("claimed_by", sa.String(length=128), nullable=True))
    if "available_at" not in existing:
        op.add_column(
            "analysis_jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("available_at")
        batch.drop_column("claimed_by")
