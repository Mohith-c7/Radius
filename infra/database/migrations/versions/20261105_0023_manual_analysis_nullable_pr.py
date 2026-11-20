"""Allow manual analyses that have no GitHub pull request."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_0023"
down_revision: str | None = "20261119_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("analyses") as batch:
        batch.alter_column(
            "pull_request_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM analyses WHERE pull_request_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Cannot restore NOT NULL while manual analyses exist.")
    with op.batch_alter_table("analyses") as batch:
        batch.alter_column(
            "pull_request_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
