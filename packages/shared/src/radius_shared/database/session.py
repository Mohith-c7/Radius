"""Database engine and session factory helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import Field, field_validator
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from radius_shared.config import RadiusBaseSettings


def normalize_database_url(url: str) -> str:
    """Force the psycopg driver for plain Postgres URLs (e.g. from Neon)."""

    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


class DatabaseSettings(RadiusBaseSettings):
    """Database settings shared by API and worker processes."""

    database_url: str = Field(
        default="postgresql+psycopg://radius:radius@localhost:5432/radius",
        alias="DATABASE_URL",
    )

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine from settings."""

    return create_engine(normalize_database_url(settings.database_url), pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
