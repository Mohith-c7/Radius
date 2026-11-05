"""SQLAlchemy database setup for Radius application services."""
from radius_shared.database.session import normalize_database_url
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
# C-14: the same URL normalisation as the domain engine, the worker and Alembic
# (``postgres://`` -> ``postgresql+psycopg://``), and connection health checks so
# a database restart does not leave sign-in returning 500s until the pool recycles.
DATABASE_URL = normalize_database_url(settings.database_url)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
