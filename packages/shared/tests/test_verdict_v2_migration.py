"""Migrations 20261102_0013 and 0014 (verdict_v2, verdict_v2_requests): chain, up, down, parity."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect

TABLES = {"verdict_v2", "verdict_v2_requests"}


def _root() -> Path:
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )


def _load(name: str):
    path = _root() / "infra/database/migrations/versions" / name
    spec = importlib.util.spec_from_file_location(f"mig_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(conn) -> None:
    other = [t for n, t in metadata.tables.items() if n not in TABLES]
    metadata.create_all(conn, tables=other)


def test_chain_is_linear_with_one_head() -> None:
    m13 = _load("20261102_0013_verdict_v2.py")
    m14 = _load("20261102_0014_verdict_v2_requests.py")
    assert (m13.revision, m13.down_revision) == ("20261102_0013", "20261102_0012")
    assert (m14.revision, m14.down_revision) == ("20261102_0014", "20261102_0013")
    script = ScriptDirectory(str(_root() / "infra/database/migrations"))
    assert len(script.get_heads()) == 1


def test_upgrade_matches_models_and_downgrade_drops_tables() -> None:
    mods = [
        _load("20261102_0013_verdict_v2.py"),
        _load("20261102_0014_verdict_v2_requests.py"),
    ]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        _prepare(conn)
        with Operations.context(MigrationContext.configure(conn)):
            for module in mods:
                module.upgrade()
            assert TABLES <= set(inspect(conn).get_table_names())
            assert compare_metadata(MigrationContext.configure(conn), metadata) == []
            for module in reversed(mods):
                module.downgrade()
            names = set(inspect(conn).get_table_names())
            assert not TABLES & names
            assert "analyses" in names
            for module in mods:  # re-applicable
                module.upgrade()
            assert TABLES <= set(inspect(conn).get_table_names())


def test_constraints_and_tenant_indexes_exist() -> None:
    mods = [
        _load("20261102_0013_verdict_v2.py"),
        _load("20261102_0014_verdict_v2_requests.py"),
    ]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        _prepare(conn)
        with Operations.context(MigrationContext.configure(conn)):
            for module in mods:
                module.upgrade()
        inspector = inspect(conn)
        for table in TABLES:
            cols = {c["name"]: c for c in inspector.get_columns(table)}
            assert cols["organization_id"]["nullable"] is False
            assert ["organization_id"] in [
                i["column_names"] for i in inspector.get_indexes(table)
            ]
        uniques = {
            tuple(u["column_names"]) for u in inspector.get_unique_constraints("verdict_v2")
        }
        assert ("analysis_id", "revision") in uniques
        assert ("analysis_id", "inputs_digest") in uniques
        request_uniques = {
            tuple(u["column_names"])
            for u in inspector.get_unique_constraints("verdict_v2_requests")
        }
        assert ("analysis_id",) in request_uniques
        conn.execute(sa.text("select 1"))
