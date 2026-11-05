"""Create the sign-in tables (auth_*) in the migration history, if they are missing.

Revision ID: 20261103_0019
Revises: 20261103_0018
Create Date: 2026-11-03

C-13: ``auth_users``, ``auth_accounts``, ``auth_tokens``, ``auth_oauth_flows`` and
``auth_sessions`` were created only by ``create_all`` at API start, so no revision could ever
alter them. This revision creates each table (and index) only when it does not exist, so it is
safe on a database where the API already created them, and ``create_all`` stays harmless.
Models: ``apps/api/src/app/models.py``. Downgrade does NOT drop the tables (they may hold
accounts created before this revision). The revision number may be renumbered at merge time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0019"
down_revision: str | None = "20261103_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _ensure_index(name: str, table: str, columns: list[str], *, unique: bool) -> None:
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "auth_users" not in tables:
        op.create_table(
            "auth_users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_auth_users_email", "auth_users", ["email"], unique=True)
    if "auth_accounts" not in tables:
        op.create_table(
            "auth_accounts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("provider", sa.String(length=24), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=False),
            _ts("created_at"),
            sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "provider_account_id", name="uq_provider_account"),
        )
    _ensure_index("ix_auth_accounts_user_id", "auth_accounts", ["user_id"], unique=False)
    if "auth_tokens" not in tables:
        op.create_table(
            "auth_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            _ts("expires_at"),
            _ts("used_at", nullable=True),
            _ts("created_at"),
            sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"], unique=False)
    _ensure_index("ix_auth_tokens_purpose", "auth_tokens", ["purpose"], unique=False)
    _ensure_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)
    if "auth_oauth_flows" not in tables:
        op.create_table(
            "auth_oauth_flows",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("flow_hash", sa.String(length=64), nullable=False),
            sa.Column("state_hash", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=24), nullable=False),
            sa.Column("nonce", sa.String(length=128), nullable=False),
            sa.Column("code_verifier", sa.String(length=128), nullable=False),
            sa.Column("next_path", sa.String(length=512), nullable=False),
            _ts("expires_at"),
            _ts("created_at"),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_auth_oauth_flows_flow_hash", "auth_oauth_flows", ["flow_hash"], unique=True)
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            _ts("expires_at"),
            _ts("revoked_at", nullable=True),
            _ts("created_at"),
            sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    # Deliberately empty: the tables may predate this revision and hold accounts.
    pass
