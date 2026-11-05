"""C-17: migrations take a PostgreSQL advisory lock; other dialects are untouched."""

from types import SimpleNamespace

from radius_shared.database.migration_lock import (
    MIGRATION_LOCK_KEY,
    acquire_migration_lock,
)
from sqlalchemy import create_engine


class _FakeConnection:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = SimpleNamespace(name=dialect_name)
        self.statements: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))


def test_postgresql_takes_a_transaction_scoped_advisory_lock() -> None:
    connection = _FakeConnection("postgresql")
    assert acquire_migration_lock(connection) is True
    [(sql, params)] = connection.statements
    assert "pg_advisory_xact_lock" in sql  # released at commit/rollback, never leaked
    assert params == {"key": MIGRATION_LOCK_KEY}


def test_other_dialects_do_nothing() -> None:
    connection = _FakeConnection("mysql")
    assert acquire_migration_lock(connection) is False
    assert connection.statements == []


def test_sqlite_connection_is_untouched() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        assert acquire_migration_lock(connection) is False


def test_migration_env_calls_the_lock_inside_the_transaction() -> None:
    from pathlib import Path

    root = next(p for p in Path(__file__).resolve().parents if (p / "infra" / "database" / "migrations").is_dir())
    env = (root / "infra/database/migrations/env.py").read_text(encoding="utf-8")
    begin = env.index("with context.begin_transaction():\n            # C-17")
    assert env.index("acquire_migration_lock(connection)", begin) < env.index("context.run_migrations()", begin)
