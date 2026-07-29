"""Worker orchestration tests."""

from pathlib import Path
from uuid import uuid4

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import StartAnalysisCommand
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
from radius_testing.application import TestingApplicationService as RadiusTestingService
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


def test_phase1_orchestrator_executes_backend_spine(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    analysis_store = InMemoryAnalysisStore()
    graph_store = InMemoryGraphStore()
    analysis_service = AnalysisApplicationService(
        analysis_store,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(
            repository_id=uuid4(),
            pull_request_id=uuid4(),
            commit_sha="a" * 40,
        )
    )
    orchestrator = Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(),
            default_language_parser_registry(),
        ),
        graph_service=GraphApplicationService(graph_store),
        graph_store=graph_store,
        testing_service=RadiusTestingService(
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

    result = orchestrator.execute(
        ExecuteAnalysisCommand(
            analysis_id=analysis.id,
            repository_id=analysis.repository_id,
            repository_path=tmp_path,
            diff_text="""diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1 +1,2 @@
 def calculate():
+    return 2
""",
        )
    )

    saved = analysis_store.get_by_id(analysis.id)
    assert saved.status.value == "completed"
    assert result.changed_file_count == 1
    assert result.affected_files == 3
    assert result.selected_tests == 3
    assert result.risk_level in {"low", "medium", "high", "critical"}


def test_in_memory_analysis_queue_claims_each_analysis_once() -> None:
    queue = InMemoryAnalysisQueue()
    analysis_id = uuid4()

    queue.enqueue(analysis_id)
    queue.enqueue(analysis_id)

    assert len(queue) == 1
    assert queue.claim_next() == analysis_id
    assert queue.claim_next() is None


def _write_repository(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "core.py").write_text(
        "def calculate():\n    return 1\n",
        encoding="utf-8",
    )
    (root / "src" / "service.py").write_text(
        "from src.core import calculate\n\ndef handle():\n    return calculate()\n",
        encoding="utf-8",
    )
    (root / "src" / "api.py").write_text(
        "from src.service import handle\n\ndef route():\n    return handle()\n",
        encoding="utf-8",
    )
    for name in ("test_core.py", "test_service.py", "test_api.py"):
        (root / "tests" / name).write_text(
            "def test_placeholder():\n    assert True\n",
            encoding="utf-8",
        )
