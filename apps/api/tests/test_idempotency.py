"""Idempotency infrastructure tests."""

from radius_api.idempotency import SqlAlchemyIdempotencyStore
from radius_shared.database.base import Base
from radius_shared.database.models import Organization
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_idempotency_store_saves_and_reads_response() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organization = Organization(name="Acme")
        session.add(organization)
        session.flush()
        store = SqlAlchemyIdempotencyStore(session)

        saved = store.save(
            organization.id,
            "key-1",
            "start_analysis",
            "a" * 64,
            202,
            {"success": True, "data": {"id": "analysis-id"}},
        )
        loaded = store.get(organization.id, "key-1", "start_analysis")

        assert loaded == saved
        assert loaded.response_body["data"]["id"] == "analysis-id"
