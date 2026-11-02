"""LK-04: the optional, flag-gated test-assertion extraction step of the worker orchestrator."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest
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
from radius_worker import orchestrator as orchestrator_module
from radius_worker.config import WorkerSettings
from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)

DIFF = """diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1,2 +1,2 @@
 def calculate():
-    return 1
+    return 2
"""


def _build(tmp_path: Path, *, enabled: bool) -> tuple[Phase1AnalysisOrchestrator, ExecuteAnalysisCommand]:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "core.py").write_text("def calculate():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_x():\n    assert calculate() == 2\n\n\ndef test_empty():\n    pass\n", encoding="utf-8"
    )
    graph_store = InMemoryGraphStore()
    analysis_service = AnalysisApplicationService(
        InMemoryAnalysisStore(), change_analyzer=UnifiedDiffChangeAnalyzer()
    )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(repository_id=uuid4(), pull_request_id=uuid4(), commit_sha="a" * 40)
    )
    orchestrator = Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(), default_language_parser_registry()
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
            scorer=DeterministicConfidenceScorer(), store=InMemoryConfidenceStore()
        ),
        execute_tests=False,
        assertion_extraction_enabled=enabled,
    )
    command = ExecuteAnalysisCommand(
        analysis_id=analysis.id,
        repository_id=analysis.repository_id,
        repository_path=tmp_path,
        diff_text=DIFF,
    )
    return orchestrator, command


def test_flag_defaults_to_off() -> None:
    field = WorkerSettings.model_fields["assertion_extraction_enabled"]
    assert field.default is False
    assert field.alias == "RADIUS_FEATURE_ASSERTION_EXTRACTION"


def test_flag_off_never_runs_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("extraction must not run when the flag is off")

    monkeypatch.setattr(orchestrator_module, "extract_assertions", boom)
    orchestrator, command = _build(tmp_path, enabled=False)
    orchestrator.execute(command)


def test_flag_on_logs_counts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    orchestrator, command = _build(tmp_path, enabled=True)
    with caplog.at_level(logging.INFO):
        orchestrator.execute(command)
    records = [r for r in caplog.records if r.getMessage() == "Test assertions extracted"]
    assert len(records) == 1
    record = records[0]
    assert record.assertions == 1
    assert record.tests == 2
    assert record.tests_without_assertions == 1
    assert record.algo_version == "assertion-extract-v1"


def test_extraction_failure_never_fails_the_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(orchestrator_module, "extract_assertions", boom)
    orchestrator, command = _build(tmp_path, enabled=True)
    with caplog.at_level(logging.WARNING):
        result = orchestrator.execute(command)
    assert result.changed_file_count == 1
    assert any("Assertion extraction failed" in r.getMessage() for r in caplog.records)
