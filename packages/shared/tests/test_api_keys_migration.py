"""Migration 0015 creates and drops the managed API key tables (up and down)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from radius_shared.database.api_keys import ApiKey, ApiKeyAuditEvent
from sqlalchemy import create_engine, inspect


def _load():
    root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )
    path = root / "infra/database/migrations/versions/20261102_0015_api_keys.py"
    spec = importlib.util.spec_from_file_location("mig_0015", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_keys_migration_up_and_down_matches_models() -> None:
    module = _load()
    assert module.down_revision == "20261102_0014"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("create table organizations (id char(32) primary key)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            inspector = inspect(conn)
            for model in (ApiKey, ApiKeyAuditEvent):
                table = model.__table__
                cols = {c["name"] for c in inspector.get_columns(table.name)}
                assert cols == {c.name for c in table.columns}
                idx = {i["name"] for i in inspector.get_indexes(table.name)}
                assert {i.name for i in table.indexes} <= idx
            uniques = {u["name"] for u in inspector.get_unique_constraints("api_keys")}
            assert "uq_api_keys_org_prefix" in uniques
            assert not any(
                "plaintext" in c or c == "token"
                for c in {c["name"] for c in inspector.get_columns("api_keys")}
            )
            module.downgrade()
            assert "api_keys" not in inspect(conn).get_table_names()
            assert "api_key_audit_events" not in inspect(conn).get_table_names()
