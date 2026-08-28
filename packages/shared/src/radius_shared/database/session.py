"""Database engine and session factory helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import Field
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from radius_shared.config import RadiusBaseSettings


class DatabaseSettings(RadiusBaseSettings):
    """Database settings shared by API and worker processes."""

    database_url: str = Field(
        default="postgresql+psycopg://radius:radius@localhost:5432/radius",
        alias="DATABASE_URL",
    )


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine from settings."""

    return create_engine(settings.database_url, pool_pre_ping=True)


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
