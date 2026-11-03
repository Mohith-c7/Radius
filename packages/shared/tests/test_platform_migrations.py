"""Migrations 20261103_0017..0020 (C-02/C-05, C-12, C-13, C-15): chain, data safety, model parity."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from radius_shared.database import coverage, intent, models, verdict_v2  # noqa: F401
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect, text


def _root() -> Path:
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    )


def _table_of(obj) -> str:
    return getattr(obj, "name", "") if type(obj).__name__ == "Table" else getattr(getattr(obj, "table", None), "name", "")


def _domain_only(obj, name, type_, reflected, compare_to) -> bool:
    return not (_table_of(obj) or name or "").startswith("auth_")


def _auth_only(obj, name, type_, reflected, compare_to) -> bool:
    return (_table_of(obj) or name or "").startswith("auth_")


@pytest.fixture
def db(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_root() / "infra" / "database" / "migrations"))
    return config, create_engine(url)


def test_full_chain_matches_the_models(db) -> None:
    config, engine = db
    command.upgrade(config, "head")
    with engine.connect() as conn:
        domain = MigrationContext.configure(conn, opts={"include_object": _domain_only})
        diffs = compare_metadata(domain, metadata)
        assert diffs == [], diffs  # includes users.github_user_id nullability (C-15)
        # The auth_* tables (own metadata) match their models too (C-13).
        import app.models  # noqa: F401
        from app.database import Base as AuthBase

        auth = MigrationContext.configure(conn, opts={"include_object": _auth_only})
        assert compare_metadata(auth, AuthBase.metadata) == []
        inspector = inspect(conn)
        assert {"claimed_by", "available_at"} <= {
            c["name"] for c in inspector.get_columns("analysis_jobs")
        }
        index = {i["name"]: i for i in inspector.get_indexes("analyses")}["uq_analyses_active_pr_commit"]
        assert index["unique"] == 1 and index["column_names"] == ["pull_request_id", "commit_sha"]
        assert {
            "auth_users",
            "auth_accounts",
            "auth_tokens",
            "auth_oauth_flows",
            "auth_sessions",
        } <= set(inspector.get_table_names())
        users = {c["name"]: c for c in inspector.get_columns("users")}
        assert users["github_user_id"]["nullable"] is True


def test_downgrade_and_upgrade_again_is_clean(db) -> None:
    config, _engine = db
    command.upgrade(config, "head")
    command.downgrade(config, "20261103_0016")
    command.upgrade(config, "head")


def _insert(conn, table: str, **values) -> None:
    """Insert one row, filling any other NOT NULL column with a neutral value."""

    for column in inspect(conn).get_columns(table):
        name = column["name"]
        if name in values or column["nullable"] or column.get("default") is not None:
            continue
        kind = str(column["type"]).upper()
        if "DATETIME" in kind or "TIMESTAMP" in kind:
            values[name] = "2026-01-01 00:00:00"
        elif "INT" in kind:
            values[name] = 0
        elif "BOOL" in kind:
            values[name] = 0
        else:
            values[name] = "x"
    columns = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({marks})"), values)


def _seed_duplicates(engine) -> None:
    with engine.begin() as conn:
        _insert(conn, "organizations", id="o1", name="Acme")
        _insert(
            conn, "repositories", id="r1", organization_id="o1", github_repository_id=1,
            provider="github", visibility="private", status="connected",
        )
        _insert(conn, "pull_requests", id="p1", repository_id="r1", github_pr_number=1, status="open")
        for idx, created in enumerate(["2026-01-01 00:00:01", "2026-01-01 00:00:02", "2026-01-01 00:00:03"]):
            _insert(
                conn, "analyses", id=f"a{idx}", repository_id="r1", pull_request_id="p1",
                commit_sha="f" * 40, status="pending" if idx < 2 else "completed",
                started_at=created, created_at=created,
            )
            _insert(conn, "analysis_jobs", id=f"j{idx}", analysis_id=f"a{idx}", status="pending", attempts=0)


def test_existing_duplicate_active_analyses_are_cancelled_not_deleted(db) -> None:
    config, engine = db
    command.upgrade(config, "20261103_0017")
    _seed_duplicates(engine)
    command.upgrade(config, "20261103_0018")
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, status FROM analyses")).all())
        assert rows == {"a0": "pending", "a1": "cancelled", "a2": "completed"}  # oldest kept
        jobs = dict(conn.execute(text("SELECT id, status FROM analysis_jobs")).all())
        assert jobs == {"j0": "pending", "j1": "completed", "j2": "pending"}
        error = conn.execute(text("SELECT last_error FROM analysis_jobs WHERE id='j1'")).scalar()
        assert error.startswith("Cancelled: duplicate")


def test_auth_tables_migration_is_idempotent_with_create_all(db) -> None:
    config, engine = db
    command.upgrade(config, "20261103_0018")
    # The API's create_all already made the tables (an existing install) ...
    import app.models  # noqa: F401
    from app.database import Base as AuthBase  # the auth metadata

    AuthBase.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth_users (id, name, email, email_verified, role, created_at, updated_at) "
                "VALUES ('u1','A','a@example.test',1,'developer','2026-01-01','2026-01-01')"
            )
        )
    # ... and the migration must neither fail nor touch them.
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM auth_users")).scalar() == 1
    # A second create_all after the migration stays harmless.
    AuthBase.metadata.create_all(bind=engine)


def test_github_user_id_values_survive_the_nullable_migration(db) -> None:
    config, engine = db
    command.upgrade(config, "20261103_0019")
    with engine.begin() as conn:
        _insert(conn, "organizations", id="o1", name="Acme")
        _insert(conn, "users", id="u1", organization_id="o1", github_user_id=77, email="a@example.test", role="developer")
    command.upgrade(config, "head")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT github_user_id FROM users")).scalar() == 77
        _insert(conn, "users", id="u2", organization_id="o1", github_user_id=None, email="b@example.test", role="developer")
        _insert(conn, "users", id="u3", organization_id="o1", github_user_id=None, email="c@example.test", role="developer")


def test_provider_login_column_is_added_keeps_rows_and_is_idempotent(db) -> None:
    config, engine = db
    command.upgrade(config, "20261103_0020")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth_users (id, name, email, email_verified, role, created_at, updated_at) "
                "VALUES ('u1','A','a@example.test',1,'developer','2026-01-01','2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO auth_accounts (id, user_id, provider, provider_account_id, created_at) "
                "VALUES ('a1','u1','github','5','2026-01-01')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT provider_account_id, provider_login FROM auth_accounts")).one()
    assert tuple(row) == ("5", None)  # existing links stay, login unknown until the next sign-in
    command.downgrade(config, "20261103_0020")
    command.upgrade(config, "head")  # idempotent after a downgrade
    assert "provider_login" in {c["name"] for c in inspect(engine).get_columns("auth_accounts")}
