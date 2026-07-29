"""FastAPI dependency wiring for Radius services."""

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
)
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
    SqlAlchemyConfidenceStore,
)
from radius_graph.infrastructure import InMemoryGraphStore, SqlAlchemyGraphStore
from radius_repository.application import RepositoryApplicationService
from radius_repository.infrastructure import (
    InMemoryRepositoryStore,
    SqlAlchemyRepositoryStore,
)
from radius_shared.database.session import (
    create_database_engine,
    create_session_factory,
)
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    SqlAlchemyTestStore,
    StaticTestCommandPlanner,
)
from radius_worker.queue import InMemoryAnalysisQueue
from sqlalchemy.orm import Session, sessionmaker


@dataclass(slots=True)
class AppContainer:
    """Application service container for API runtime wiring."""

    repository_store: InMemoryRepositoryStore = field(
        default_factory=InMemoryRepositoryStore
    )
    analysis_store: InMemoryAnalysisStore = field(default_factory=InMemoryAnalysisStore)
    analysis_queue: InMemoryAnalysisQueue = field(default_factory=InMemoryAnalysisQueue)
    graph_store: InMemoryGraphStore = field(default_factory=InMemoryGraphStore)
    test_store: InMemoryTestStore = field(default_factory=InMemoryTestStore)
    confidence_store: InMemoryConfidenceStore = field(
        default_factory=InMemoryConfidenceStore
    )
    session_factory: sessionmaker[Session] | None = None

    def repository_service(self) -> RepositoryApplicationService:
        """Return repository application service."""

        return RepositoryApplicationService(self.repository_store)

    def analysis_service(self) -> AnalysisApplicationService:
        """Return analysis application service."""

        return AnalysisApplicationService(
            self.analysis_store,
            pipeline=self.analysis_queue,
        )

    def testing_service(self) -> TestingApplicationService:
        """Return testing application service."""

        return TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=self.test_store,
            planner=StaticTestCommandPlanner(),
        )

    def confidence_service(self) -> ConfidenceApplicationService:
        """Return confidence application service."""

        return ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=self.confidence_store,
        )


def get_container(request: Request) -> AppContainer:
    """Return the app service container."""

    return request.app.state.container


def configure_sql_storage(container: AppContainer, settings: Any) -> None:
    """Configure SQL-backed stores for production runtime."""

    engine = create_database_engine(settings)
    container.session_factory = create_session_factory(engine)


def _new_session(container: AppContainer) -> Session:
    if container.session_factory is None:
        msg = "SQL storage is not configured."
        raise RuntimeError(msg)
    return container.session_factory()


def get_repository_service(request: Request):
    """Return repository application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.repository_service()
        return
    session = _new_session(container)
    try:
        yield RepositoryApplicationService(SqlAlchemyRepositoryStore(session))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_analysis_service(request: Request):
    """Return analysis application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.analysis_service()
        return
    session = _new_session(container)
    try:
        yield AnalysisApplicationService(
            SqlAlchemyAnalysisStore(session),
            pipeline=SqlAlchemyAnalysisJobQueue(session),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_testing_service(request: Request):
    """Return testing application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.testing_service()
        return
    session = _new_session(container)
    try:
        yield TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=SqlAlchemyTestStore(session),
            planner=StaticTestCommandPlanner(),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_confidence_service(request: Request):
    """Return confidence application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.confidence_service()
        return
    session = _new_session(container)
    try:
        yield ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=SqlAlchemyConfidenceStore(session),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_graph_store(request: Request):
    """Return graph store."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.graph_store
        return
    session = _new_session(container)
    try:
        yield SqlAlchemyGraphStore(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
