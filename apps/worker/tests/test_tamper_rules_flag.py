"""EV-02: the optional, flag-gated tamper-rules step of the worker orchestrator."""

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

DIFF = """diff --git a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1,2 +1,2 @@
 def test_x():
-    assert calculate() == 2
+    assert calculate() is not None
"""


def _build(
    tmp_path: Path, *, tamper: bool, symbols: bool = False
) -> tuple[Phase1AnalysisOrchestrator, ExecuteAnalysisCommand]:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "core.py").write_text("def calculate():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_x():\n    assert calculate() is not None\n", encoding="utf-8"
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
        symbol_changes_enabled=symbols,
        tamper_rules_enabled=tamper,
    )
    command = ExecuteAnalysisCommand(
        analysis_id=analysis.id,
        repository_id=analysis.repository_id,
        repository_path=tmp_path,
        diff_text=DIFF,
    )
    return orchestrator, command


def test_flag_defaults_to_off() -> None:
    field = WorkerSettings.model_fields["tamper_rules_enabled"]
    assert field.default is False
    assert field.alias == "RADIUS_FEATURE_TAMPER_RULES"


def test_flag_off_never_runs_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tamper analysis must not run when the flag is off")

    monkeypatch.setattr(orchestrator_module, "analyze_tampering", boom)
    orchestrator, command = _build(tmp_path, tamper=False)
    orchestrator.execute(command)


def test_flag_on_logs_counts_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    orchestrator, command = _build(tmp_path, tamper=True)
    with caplog.at_level(logging.INFO):
        orchestrator.execute(command)
    records = [r for r in caplog.records if r.getMessage() == "Tamper rules evaluated"]
    assert len(records) == 1
    record = records[0]
    assert record.catalog_version == "tamper-rules-v1"
    assert record.findings == 1
    assert record.by_rule == {"T004": 1}
    # the symbol-change log line is not emitted unless its own flag is on
    assert not [r for r in caplog.records if r.getMessage() == "Symbol changes extracted"]


def test_both_flags_log_both_steps(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    orchestrator, command = _build(tmp_path, tamper=True, symbols=True)
    with caplog.at_level(logging.INFO):
        orchestrator.execute(command)
    messages = {r.getMessage() for r in caplog.records}
    assert {"Symbol changes extracted", "Tamper rules evaluated"} <= messages


def test_tamper_failure_never_fails_the_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("rule engine exploded")

    monkeypatch.setattr(orchestrator_module, "analyze_tampering", boom)
    orchestrator, command = _build(tmp_path, tamper=True)
    with caplog.at_level(logging.WARNING):
        result = orchestrator.execute(command)
    assert result.changed_file_count == 1
    assert any("Tamper analysis failed" in r.getMessage() for r in caplog.records)


def test_extraction_failure_skips_tamper_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(orchestrator_module, "extract_symbol_changes", boom)
    orchestrator, command = _build(tmp_path, tamper=True)
    with caplog.at_level(logging.INFO):
        orchestrator.execute(command)
    assert not [r for r in caplog.records if r.getMessage() == "Tamper rules evaluated"]
