"""Alembic environment for Radius."""

import sys
from logging.config import fileConfig
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure all workspace packages are importable when Alembic is run directly
# (e.g. `uv run alembic -c alembic.ini current`).  Alembic's own
# prepend_sys_path only adds a single directory; this loop adds every
# packages/<pkg>/src directory so radius_shared (and siblings) resolve.
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parents[3]  # …/Radius
for _src in sorted(_repo_root.glob("packages/*/src")):
    _src_str = str(_src)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)

from alembic import context  # noqa: E402
from radius_shared.database import coverage, models  # noqa: F401, E402
from radius_shared.database.base import metadata  # noqa: E402
from sqlalchemy import engine_from_config, pool  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def get_database_url() -> str:
    """Return database URL from config or environment."""

    from os import getenv

    url = getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations without a DBAPI connection."""

    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a DBAPI connection."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
