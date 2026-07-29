"""Worker runtime shell."""

import time
from collections.abc import Callable

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
    SubprocessTestRunner,
)

from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)
from radius_worker.queue import InMemoryAnalysisQueue


def run_worker() -> None:
    """Start the worker process.

    The foundation implementation intentionally exposes only a startup shell.
    Analysis orchestration will be added once domain contracts are in place.
    """

    print("Radius worker ready")


def run_worker_once(
    *,
    queue,
    orchestrator: Phase1AnalysisOrchestrator,
    command_loader: Callable[[object], ExecuteAnalysisCommand],
) -> bool:
    """Claim, execute, and acknowledge one analysis job."""

    job = queue.claim_next()
    if job is None:
        return False
    analysis_id = job.analysis_id if hasattr(job, "analysis_id") else job
    try:
        orchestrator.execute(command_loader(job))
    except Exception as exc:
        if hasattr(queue, "fail"):
            queue.fail(analysis_id, str(exc))
        raise
    if hasattr(queue, "complete"):
        queue.complete(analysis_id)
    return True


def run_worker_loop(
    *,
    queue,
    orchestrator: Phase1AnalysisOrchestrator,
    command_loader: Callable[[object], ExecuteAnalysisCommand],
    poll_interval_seconds: float = 2.0,
    stop_after_idle_cycles: int | None = None,
) -> None:
    """Run a polling worker loop with optional bounded idle cycles for tests."""

    idle_cycles = 0
    while True:
        processed = run_worker_once(
            queue=queue,
            orchestrator=orchestrator,
            command_loader=command_loader,
        )
        if processed:
            idle_cycles = 0
            continue
        idle_cycles += 1
        if stop_after_idle_cycles is not None and idle_cycles >= stop_after_idle_cycles:
            return
        time.sleep(poll_interval_seconds)


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
            runner=SubprocessTestRunner(),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=InMemoryConfidenceStore(),
        ),
    )
