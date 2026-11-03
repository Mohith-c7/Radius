"""Serialise concurrent ``alembic upgrade`` runs on PostgreSQL (C-17)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

#: Arbitrary constant application key for ``pg_advisory_xact_lock`` ("radius" as digits).
MIGRATION_LOCK_KEY = 7_265_200_517


def acquire_migration_lock(connection: Connection) -> bool:
    """Take a transaction-scoped advisory lock; blocks while another migrator holds it.

    Call inside the migration transaction BEFORE Alembic reads the current revision:
    a second API replica that starts at the same time then waits, and afterwards finds
    the database already upgraded instead of re-applying a revision. The lock is released
    automatically at commit or rollback. Returns ``False`` (nothing to do) on dialects
    without advisory locks, for example SQLite.
    """

    if connection.dialect.name != "postgresql":
        return False
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
    return True
