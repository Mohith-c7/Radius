"""Add organizations.github_installation_status

Tracks whether the organization's GitHub App installation is ``active``,
``suspended`` or ``deleted`` so webhooks and the worker stop accepting or
running analyses for a removed installation without deleting any data.
Existing rows become ``active``.

Revision ID: 20261102_0011
Revises: 20261102_0010
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0011"
down_revision: str | None = "20261102_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "github_installation_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("github_installation_status")
