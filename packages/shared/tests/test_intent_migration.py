"""Migration 20261102_0011 (intent persistence): chain, up, down, model parity."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect

INTENT_TABLES = {
    "intent_sources",
    "intent_snapshots",
    "intent_snapshot_sources",
    "intent_criteria",
    "intent_criterion_state_changes",
}


def _root() -> Path:
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )


def _load():
    path = (
        _root()
        / "infra/database/migrations/versions/20261102_0011_intent_persistence.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0011", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(conn) -> None:
    """Create every non-intent table, as the previous migrations would have."""
    other = [t for n, t in metadata.tables.items() if n not in INTENT_TABLES]
    metadata.create_all(conn, tables=other)


def test_revision_chain_has_single_head() -> None:
    module = _load()
    assert module.revision == "20261102_0011"
    assert module.down_revision == "20261102_0010"
    script = ScriptDirectory(str(_root() / "infra/database/migrations"))
    assert len(script.get_heads()) == 1  # later migrations may extend the chain


def test_upgrade_creates_tables_matching_models_and_downgrade_drops_them() -> None:
    module = _load()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        _prepare(conn)
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            assert INTENT_TABLES <= set(inspect(conn).get_table_names())
            diff = compare_metadata(MigrationContext.configure(conn), metadata)
            assert diff == []
            module.downgrade()
            names = set(inspect(conn).get_table_names())
            assert not INTENT_TABLES & names
            assert "analyses" in names
            module.upgrade()  # re-applicable after a downgrade
            assert INTENT_TABLES <= set(inspect(conn).get_table_names())


def test_constraints_and_indexes_exist_after_upgrade() -> None:
    module = _load()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        _prepare(conn)
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        inspector = inspect(conn)
        for table in INTENT_TABLES:
            cols = {c["name"] for c in inspector.get_columns(table)}
            assert "organization_id" in cols
            index_cols = [i["column_names"] for i in inspector.get_indexes(table)]
            assert ["organization_id"] in index_cols
        uniques = {
            tuple(u["column_names"])
            for u in inspector.get_unique_constraints("intent_criteria")
        }
        assert ("snapshot_id", "criterion_id") in uniques
        snapshot_uniques = {
            tuple(u["column_names"])
            for u in inspector.get_unique_constraints("intent_snapshots")
        }
        assert ("analysis_id", "content_hash") in snapshot_uniques
        assert ("analysis_id", "version") in snapshot_uniques
        assert ["analysis_id"] in [
            i["column_names"] for i in inspector.get_indexes("intent_snapshots")
        ]
        conn.execute(sa.text("select 1"))
