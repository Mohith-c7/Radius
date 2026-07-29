"""Worker runtime shell."""

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    UnifiedDiffChangeAnalyzer,
)
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_graph.application import GraphApplicationService
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)

from radius_worker.orchestrator import Phase1AnalysisOrchestrator
from radius_worker.queue import InMemoryAnalysisQueue


def run_worker() -> None:
    """Start the worker process.

    The foundation implementation intentionally exposes only a startup shell.
    Analysis orchestration will be added once domain contracts are in place.
    """

    print("Radius worker ready")


def create_local_orchestrator(
    queue: InMemoryAnalysisQueue | None = None,
) -> Phase1AnalysisOrchestrator:
    """Create an in-memory worker orchestrator for local development/tests."""

    graph_store = InMemoryGraphStore()
    analysis_service = AnalysisApplicationService(
        InMemoryAnalysisStore(),
        pipeline=queue,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    return Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(),
            default_language_parser_registry(),
        ),
        graph_service=GraphApplicationService(graph_store),
        graph_store=graph_store,
        testing_service=TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=InMemoryTestStore(),
            planner=StaticTestCommandPlanner(),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=InMemoryConfidenceStore(),
        ),
    )
