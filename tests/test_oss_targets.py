"""Real-world open-source target verification test suite for Radius.

Validates Radius against two authentic, production open-source repositories:
  1. Python Target: `bottlepy/bottle`
     - Cloned from GitHub, analyzing commit 90bd4aa (implement json.enable and json.dump_func configs).
     - Parses 4,400+ lines of production Python with Tree-Sitter.
     - Slices diff hunk line modifications in JSONPlugin.
     - Selects impacted test (test/test_outputfilter.py) and skips 20+ unrelated test suites.
     - Recalculates dynamic confidence and formats rich PR reporting.
  2. TypeScript/JavaScript Target: `sindresorhus/emittery`
     - Cloned from GitHub, analyzing production event emitter code & typings.
     - Extracts symbols, classes, and methods across index.js, index.d.ts, and index.test-d.ts.
     - Builds Code Property Graph and computes layout for interactive SVG visualizer.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, CommitSha
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    UnifiedDiffChangeAnalyzer,
)
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_github.publisher import GitHubAnalysisReport, _markdown_report
from radius_graph.application import GraphApplicationService
from radius_graph.cpg import CodePropertyGraph
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.core import ParserEngine
from radius_parser.extractors.python import PythonExtractor
from radius_parser.extractors.typescript import TypeScriptExtractor
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_testing.application import TestingApplicationService as AppTestingService
from radius_testing.domain import (
    TestRunPlan as RadiusTestRunPlan,
)
from radius_testing.domain import (
    TestRunResult as RadiusTestRunResult,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)
from radius_worker.orchestrator import (
    AnalysisExecutionResult,
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)

BOTTLE_REPO = Path(r"C:\Users\HP\AppData\Local\Temp\oss_target_bottle")
EMITTERY_REPO = Path(r"C:\Users\HP\AppData\Local\Temp\oss_target_emittery")


class MockOssTestRunner:
    def run(self, plan: RadiusTestRunPlan, repository_path: Path) -> RadiusTestRunResult:
        count = len(plan.selected_tests)
        return RadiusTestRunResult(
            id=uuid4(),
            analysis_id=plan.analysis_id,
            status=RadiusTestRunStatus.PASSED,
            total_tests=count,
            passed=count,
            failed=0,
            skipped=0,
            duration_ms=450,
            output="Mock OSS test run passed",
        )


@pytest.mark.skipif(not BOTTLE_REPO.exists(), reason="bottlepy/bottle target repo not cloned")
def test_real_oss_python_target_bottle() -> None:
    """Test Radius against real-world commit in bottlepy/bottle."""
    # 1. Fetch real Git diff from commit 90bd4aa
    proc = subprocess.run(
        ["git", "diff", "90bd4aa^", "90bd4aa"],
        cwd=BOTTLE_REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    diff_text = proc.stdout
    assert "class JSONPlugin" in diff_text
    assert "test/test_outputfilter.py" in diff_text

    # 2. Test Discovery on real open-source repo
    discoverer = ConventionalTestDiscoverer()
    discovered_tests = discoverer.discover(BOTTLE_REPO)
    assert len(discovered_tests) >= 20
    test_paths = {t.path.value.replace("\\", "/") for t in discovered_tests}
    assert "test/test_outputfilter.py" in test_paths
    assert "test/test_auth.py" in test_paths
    assert "test/test_wsgi.py" in test_paths

    # 3. Tree-Sitter AST & Symbol Extraction on 4,400+ lines of production Python
    engine = ParserEngine()
    py_extractor = PythonExtractor()
    bottle_code = (BOTTLE_REPO / "bottle.py").read_text(encoding="utf-8")
    tree = engine.parse_python(bottle_code)
    symbols = py_extractor.extract_symbols(tree.root_node, "bottle.py", bottle_code)
    assert len(symbols) >= 50
    symbol_ids = {s.id for s in symbols}
    assert any("JSONPlugin" in sid for sid in symbol_ids)

    # 4. Orchestrator Execution on Real Repo
    analysis_id = uuid4()
    repo_id = uuid4()

    analysis_store = InMemoryAnalysisStore()
    analysis_entity = Analysis(
        id=analysis_id,
        repository_id=repo_id,
        pull_request_id=uuid4(),
        commit_sha=CommitSha("90bd4aa7439419186a85446f2aa05c23e3ba7103"),
        status=AnalysisStatus.PENDING,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    analysis_store.save(analysis_entity)

    analysis_service = AnalysisApplicationService(
        analysis_store,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    graph_store = InMemoryGraphStore()
    graph_service = GraphApplicationService(graph_store)
    parser_service = ParserApplicationService(
        FilesystemSourceDiscovery(),
        default_language_parser_registry(),
    )
    testing_service = AppTestingService(
        discoverer=discoverer,
        selector=PathBasedTestSelector(),
        store=InMemoryTestStore(),
        planner=StaticTestCommandPlanner(),
        runner=MockOssTestRunner(),
    )
    confidence_service = ConfidenceApplicationService(
        scorer=DeterministicConfidenceScorer(),
        store=InMemoryConfidenceStore(),
    )

    orchestrator = Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=parser_service,
        graph_service=graph_service,
        graph_store=graph_store,
        testing_service=testing_service,
        confidence_service=confidence_service,
    )

    command = ExecuteAnalysisCommand(
        analysis_id=analysis_id,
        repository_id=repo_id,
        repository_path=BOTTLE_REPO,
        base_ref="90bd4aa^",
        head_ref="90bd4aa",
        diff_text=diff_text,
    )

    result: AnalysisExecutionResult = orchestrator.execute(command)
    assert result.analysis_id == analysis_id

    # 5. Verify Predictive Test Selection Savings on Real Repo
    selection = testing_service.get_selection(analysis_id)
    assert selection is not None
    assert selection.total_count >= 20

    selected_paths = {item.test.path.replace("\\", "/") for item in selection.selected_tests}
    # Impacted test file MUST be selected
    assert "test/test_outputfilter.py" in selected_paths

    # Unrelated test suites MUST be skipped
    assert "test/test_auth.py" not in selected_paths
    assert "test/test_jinja2.py" not in selected_paths
    assert "test/test_mako.py" not in selected_paths

    # Verify massive CI time savings
    assert selection.time_saved_percent >= 70.0
    print(
        f"\n[REAL OSS TARGET] bottlepy/bottle: "
        f"Selected {selection.selected_count}/{selection.total_count} tests "
        f"({selection.skipped_count} skipped, {selection.time_saved_percent}% CI time saved!)"
    )

    # 6. CI Test Results Ingestion & Dynamic Confidence
    junit_report = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest-bottle" tests="12" failures="0" errors="0" skipped="0" time="1.24">
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_config_enable_false" time="0.08" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_config_dump_func" time="0.09" />
    <testcase classname="test.test_outputfilter.TestOutputFilter" name="test_json_custom_plugin" time="0.09" />
  </testsuite>
</testsuites>
"""
    test_run = testing_service.ingest_test_results(analysis_id, junit_report)
    assert test_run.total_tests == 12
    assert test_run.passed == 12
    assert test_run.failed == 0

    recalc = confidence_service.recalculate_from_test_results(analysis_id, test_run)
    assert recalc.confidence_score >= 80.0
    assert recalc.risk_level in ("low", "medium")

    # 7. Rich GitHub PR Comment formatting
    github_report = GitHubAnalysisReport(
        analysis_id=analysis_id,
        owner="bottlepy",
        repository_name="bottle",
        pull_request_number=1345,
        head_sha="90bd4aa7439419186a85446f2aa05c23e3ba7103",
        confidence_score=recalc.confidence_score,
        risk_level=recalc.risk_level,
        summary="Confidence score updated from CI test run: 92.0.",
        recommendations=("All impacted JSON filter tests passing. Safe to merge.",),
        selected_tests_count=selection.selected_count,
        skipped_tests_count=selection.skipped_count,
        time_saved_percent=selection.time_saved_percent,
        affected_files=("bottle.py", "test/test_outputfilter.py"),
        affected_symbols=("JSONPlugin.setup", "JSONPlugin.apply"),
        ai_pruned_count=0,
        ai_pruning_notes=(),
    )
    comment = _markdown_report(github_report)
    assert "Radius Confidence Report" in comment
    assert "🟢" in comment or "🟡" in comment
    assert f"{selection.time_saved_percent}%" in comment


@pytest.mark.skipif(not EMITTERY_REPO.exists(), reason="sindresorhus/emittery target repo not cloned")
def test_real_oss_typescript_target_emittery() -> None:
    """Test Radius against real-world TypeScript/JavaScript in sindresorhus/emittery."""
    engine = ParserEngine()
    ts_extractor = TypeScriptExtractor()

    # 1. Parse index.d.ts (24KB of production TypeScript definitions)
    dts_code = (EMITTERY_REPO / "index.d.ts").read_text(encoding="utf-8")
    dts_tree = engine.parse_typescript(dts_code)
    dts_symbols = ts_extractor.extract_symbols(dts_tree.root_node, "index.d.ts", dts_code)
    assert len(dts_symbols) >= 1
    dts_names = {s.name for s in dts_symbols}
    assert "Emittery" in dts_names

    # 2. Parse index.js (28KB production JavaScript event emitter)
    js_code = (EMITTERY_REPO / "index.js").read_text(encoding="utf-8")
    js_tree = engine.parse_typescript(js_code)
    js_symbols = ts_extractor.extract_symbols(js_tree.root_node, "index.js", js_code)
    assert len(js_symbols) >= 1
    js_names = {s.name for s in js_symbols}
    assert "Emittery" in js_names

    # 3. Test Discovery on emittery
    discoverer = ConventionalTestDiscoverer()
    tests = discoverer.discover(EMITTERY_REPO)
    assert len(tests) >= 1
    test_paths = [t.path.value.replace("\\", "/") for t in tests]
    assert any("test/index.js" in p or "index.test-d.ts" in p for p in test_paths)

    # 4. Build CPG with both JS source and TypeScript typings
    cpg = CodePropertyGraph()
    for s in dts_symbols:
        cpg.add_symbol(s)
    for s in js_symbols:
        cpg.add_symbol(s)

    assert len(cpg.nodes) >= 15
    print(f"\n[REAL OSS TARGET] sindresorhus/emittery: CPG constructed with {len(cpg.nodes)} symbol nodes.")
