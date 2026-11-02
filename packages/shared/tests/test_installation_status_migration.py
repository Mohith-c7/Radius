"""Migration 0012 adds organizations.github_installation_status (up and down)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )
    path = root / "infra/database/migrations/versions/20261102_0012_organization_installation_status.py"
    spec = importlib.util.spec_from_file_location("mig_0012", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installation_status_migration_up_and_down() -> None:
    module = _load()
    assert module.down_revision == "20261102_0011"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("create table organizations (id integer primary key, name text)"))
        conn.execute(sa.text("insert into organizations (id, name) values (1, 'acme')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            cols = {c["name"]: c for c in inspect(conn).get_columns("organizations")}
            assert cols["github_installation_status"]["nullable"] is False
            # Existing organizations become active.
            status = conn.execute(
                sa.text("select github_installation_status from organizations")
            ).scalar()
            assert status == "active"
            module.downgrade()
            cols = {c["name"] for c in inspect(conn).get_columns("organizations")}
            assert "github_installation_status" not in cols
            assert conn.execute(sa.text("select count(*) from organizations")).scalar() == 1
