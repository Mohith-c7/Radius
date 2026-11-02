"""Add analysis_jobs.traceparent for cross-process trace propagation

The API stores the W3C ``traceparent`` of the enqueuing span so the worker,
possibly in another process or container, continues the same trace. Nullable:
existing rows and runs with tracing disabled have no value.

Revision ID: 20261102_0010
Revises: 20261101_0009
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0010"
down_revision: str | None = "20261101_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("traceparent", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("traceparent")
