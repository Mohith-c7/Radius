"""FastAPI dependency wiring for Radius services."""

from dataclasses import dataclass, field

from fastapi import Request
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import InMemoryAnalysisStore
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_graph.infrastructure import InMemoryGraphStore
from radius_repository.application import RepositoryApplicationService
from radius_repository.infrastructure import InMemoryRepositoryStore
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)
from radius_worker.queue import InMemoryAnalysisQueue


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


def get_repository_service(request: Request) -> RepositoryApplicationService:
    """Return repository application service."""

    return get_container(request).repository_service()


def get_analysis_service(request: Request) -> AnalysisApplicationService:
    """Return analysis application service."""

    return get_container(request).analysis_service()


def get_testing_service(request: Request) -> TestingApplicationService:
    """Return testing application service."""

    return get_container(request).testing_service()


def get_confidence_service(request: Request) -> ConfidenceApplicationService:
    """Return confidence application service."""

    return get_container(request).confidence_service()
