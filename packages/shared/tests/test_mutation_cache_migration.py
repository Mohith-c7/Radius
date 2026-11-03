"""Migration 20261103_0016 (mutation_result_cache): chain, up, down, parity with the model."""

import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect

TABLE = "mutation_result_cache"


def _root() -> Path:
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )


def _migration():
    path = _root() / "infra/database/migrations/versions/20261103_0016_mutation_result_cache.py"
    spec = importlib.util.spec_from_file_location("mig_0016", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(conn) -> None:
    metadata.create_all(conn, tables=[t for n, t in metadata.tables.items() if n != TABLE])


def test_chain_is_linear_with_one_head() -> None:
    mig = _migration()
    assert (mig.revision, mig.down_revision) == ("20261103_0016", "20261102_0015")
    script = ScriptDirectory(str(_root() / "infra" / "database" / "migrations"))
    assert len(script.get_heads()) == 1  # later migrations may extend the chain
    assert script.get_revision("20261103_0016").down_revision == "20261102_0015"


def test_upgrade_matches_the_model_and_downgrade_drops_the_table() -> None:
    mig = _migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        _prepare(conn)
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            assert TABLE in inspect(conn).get_table_names()
            assert compare_metadata(MigrationContext.configure(conn), metadata) == []
            inspector = inspect(conn)
            cols = {c["name"]: c for c in inspector.get_columns(TABLE)}
            assert cols["organization_id"]["nullable"] is False
            assert cols["repository_id"]["nullable"] is False
            assert cols["cache_key"]["nullable"] is False
            uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints(TABLE)}
            assert ("organization_id", "repository_id", "cache_key") in uniques
            mig.downgrade()
            assert TABLE not in inspect(conn).get_table_names()
            assert "repositories" in inspect(conn).get_table_names()
            mig.upgrade()  # re-applicable
            assert TABLE in inspect(conn).get_table_names()
