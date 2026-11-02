"""Managed API keys and their audit trail (PRD-12).

Creates ``api_keys`` (hashed secrets, scopes, expiry, revocation, last use) and
``api_key_audit_events``. Plaintext keys are never stored. The revision number
may be renumbered at merge time if another migration lands first.

Revision ID: 20261102_0015
Revises: 20261102_0014
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0015"
down_revision: str | None = "20261102_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_api_keys_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from_id"],
            ["api_keys.id"],
            name="fk_api_keys_rotated_from_id_api_keys",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("organization_id", "prefix", name="uq_api_keys_org_prefix"),
    )
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"])
    op.create_table(
        "api_key_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_api_key_audit_events_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name="fk_api_key_audit_events_api_key_id_api_keys",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_key_audit_events"),
    )
    op.create_index(
        "ix_api_key_audit_events_organization_id",
        "api_key_audit_events",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_key_audit_events_organization_id", table_name="api_key_audit_events"
    )
    op.drop_table("api_key_audit_events")
    op.drop_index("ix_api_keys_organization_id", table_name="api_keys")
    op.drop_table("api_keys")
