"""Add test_runs.status (the runner's own run status).

Revision ID: 20261119_0022
Revises: 20261104_0021
Create Date: 2026-11-19

Without this column an ERROR run (for example the default disabled runner, a sandbox that
refused to start, or a run with unreadable reports) was read back as PASSED whenever it
recorded no failures, and its "passed" history rows fed flakiness and test history.
Nullable: rows written before this revision stay NULL and readers derive a status for them
(a row with no recorded outcome is ERROR, never PASSED). Idempotent: the column is added only
when absent. The revision number may be renumbered at merge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_0022"
down_revision: str | None = "20261104_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == "status" for c in inspector.get_columns("test_runs"))


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("test_runs") as batch:
        batch.add_column(sa.Column("status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    if not _has_column():
        return
    with op.batch_alter_table("test_runs") as batch:
        batch.drop_column("status")
