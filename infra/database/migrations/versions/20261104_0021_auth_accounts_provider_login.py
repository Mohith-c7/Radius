"""Add auth_accounts.provider_login (the provider login at the last OAuth sign-in).

Revision ID: 20261104_0021
Revises: 20261103_0020
Create Date: 2026-11-04

B-07: a criterion confirmation is attributed to the authenticated user; when that user signed in
with GitHub, the GitHub ``login`` (kept here, refreshed at every sign-in) is compared with the PR
author so an author cannot confirm their own criteria. Nullable: existing rows stay NULL until the
next sign-in, and a NULL login means "link unknown" (the documented confirm policy applies).
Idempotent: the column is added only when absent. The revision number may be renumbered at merge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0021"
down_revision: str | None = "20261103_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "auth_accounts" not in inspector.get_table_names():
        return True  # created later by create_all with the column
    return any(c["name"] == "provider_login" for c in inspector.get_columns("auth_accounts"))


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("auth_accounts") as batch:
        batch.add_column(sa.Column("provider_login", sa.String(length=64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "auth_accounts" not in inspector.get_table_names():
        return
    if any(c["name"] == "provider_login" for c in inspector.get_columns("auth_accounts")):
        with op.batch_alter_table("auth_accounts") as batch:
            batch.drop_column("provider_login")
