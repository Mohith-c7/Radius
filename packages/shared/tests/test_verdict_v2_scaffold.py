"""Verdict v2 scaffold (VS-00): flag parsing, registration, placeholder migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from radius_shared.database.base import metadata
from radius_shared.verdict_v2_flag import VerdictV2Mode, parse_verdict_v2_mode
from sqlalchemy import create_engine, inspect

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "infra" / "database" / "migrations").is_dir()
)
VERSIONS = ROOT / "infra" / "database" / "migrations" / "versions"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mig_{name}", VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, VerdictV2Mode.OFF),
        ("", VerdictV2Mode.OFF),
        ("off", VerdictV2Mode.OFF),
        ("OFF", VerdictV2Mode.OFF),
        ("false", VerdictV2Mode.OFF),
        ("0", VerdictV2Mode.OFF),
        ("no", VerdictV2Mode.OFF),
        ("typo", VerdictV2Mode.OFF),
        ("shadow", VerdictV2Mode.SHADOW),
        (" Shadow ", VerdictV2Mode.SHADOW),
        ("on", VerdictV2Mode.ON),
        ("true", VerdictV2Mode.ON),
        ("1", VerdictV2Mode.ON),
        ("yes", VerdictV2Mode.ON),
        (True, VerdictV2Mode.ON),
        (False, VerdictV2Mode.OFF),
        (VerdictV2Mode.SHADOW, VerdictV2Mode.SHADOW),
    ],
)
def test_flag_parsing_table(raw, expected) -> None:
    assert parse_verdict_v2_mode(raw) is expected


def test_database_module_is_registered_and_defines_no_table_yet() -> None:
    from radius_shared import database

    assert database.verdict_v2.__doc__
    assert "verdict_v2" not in metadata.tables
    assert "verdict_v2_requests" not in metadata.tables


def test_env_py_registers_the_verdict_v2_module() -> None:
    env = (ROOT / "infra" / "database" / "migrations" / "env.py").read_text(
        encoding="utf-8"
    )
    assert "verdict_v2" in env.split("from alembic import context")[1].split("\n\n")[0]


def test_revision_chain_is_linear_with_a_single_head() -> None:
    script = ScriptDirectory(str(ROOT / "infra" / "database" / "migrations"))
    assert len(script.get_heads()) == 1
    chain = [r.revision for r in script.walk_revisions()]
    assert chain[:3] == ["20261102_0014", "20261102_0013", "20261102_0012"] or (
        "20261102_0014" in chain
        and chain.index("20261102_0014") < chain.index("20261102_0013")
        < chain.index("20261102_0012")
    )
    mod13 = _load("20261102_0013_verdict_v2.py")
    mod14 = _load("20261102_0014_verdict_v2_requests.py")
    assert (mod13.revision, mod13.down_revision) == ("20261102_0013", "20261102_0012")
    assert (mod14.revision, mod14.down_revision) == ("20261102_0014", "20261102_0013")


def test_placeholder_migrations_upgrade_and_downgrade_on_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    modules = [
        _load("20261102_0013_verdict_v2.py"),
        _load("20261102_0014_verdict_v2_requests.py"),
    ]
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            for module in modules:
                module.upgrade()
            assert inspect(conn).get_table_names() == []
            for module in reversed(modules):
                module.downgrade()
            assert inspect(conn).get_table_names() == []
