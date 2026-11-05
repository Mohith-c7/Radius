"""Make users.github_user_id nullable (the model always said so).

Revision ID: 20261103_0020
Revises: 20261103_0019
Create Date: 2026-11-03

C-15: migration 0001 created the column NOT NULL while the model declares it optional, and
the API fabricated a number from the e-mail hash for password users. Existing values are kept.
Downgrade restores NOT NULL only when no row has NULL (otherwise it raises, nothing is lost).
The revision number may be renumbered at merge time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0020"
down_revision: str | None = "20261103_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("github_user_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("github_user_id", existing_type=sa.BigInteger(), nullable=False)
