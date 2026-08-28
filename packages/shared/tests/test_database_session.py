from radius_shared.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
    session_scope,
)
from sqlalchemy import text


def test_database_engine_and_session_scope_execute_query() -> None:
    settings = DatabaseSettings(database_url="sqlite+pysqlite:///:memory:")
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    with session_scope(session_factory) as session:
        result = session.execute(text("select 1")).scalar_one()

    assert result == 1
