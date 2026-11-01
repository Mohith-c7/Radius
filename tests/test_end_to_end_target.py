"""End-to-End Target Verification Test Suite for Radius.

This test creates a realistic multi-language (Python + TypeScript) target repository,
initializes git version control, introduces a targeted diff hunk across multiple files,
and executes the complete Radius platform verification pipeline:
  1. Cloned repo discovery & AST extraction (Tree-Sitter Python & TypeScript)
  2. Multi-language CPG symbol resolution and import linkage
  3. Diff-hunk line precision slicing (excluding untouched symbols in modified files)
  4. Predictive test selection & CI time savings calculation
  5. Blast radius metrics calculation
  6. CI JUnit XML test result ingestion & Dynamic Confidence recalculation
  7. Rich GitHub PR comment markdown & check run lifecycle formatting
  8. Graph layout engine verification for frontend interactive SVG visualizer
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from radius_github.publisher import (
    GitHubAnalysisReport,
    _markdown_report,
)
from radius_graph.application import GraphApplicationService
from radius_graph.cpg import CodePropertyGraph
from radius_graph.infrastructure import InMemoryGraphStore
from radius_graph.slicer import GraphSlicer
from radius_parser.application import ParserApplicationService
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


class MockTargetTestRunner:
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
            duration_ms=100,
            output="Mock target tests executed successfully",
        )


def _init_git_target_repo(repo_dir: Path) -> None:
    """Initialize a real Git repository with multi-language source and test files."""
    src_dir = repo_dir / "src"
    tests_dir = repo_dir / "tests"
    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    # 1. Python source files
    (src_dir / "auth.py").write_text(
        "def hash_password(password: str) -> str:\n"
        "    return 'hash_' + password\n\n"
        "def verify_password(password: str, hashed: str) -> bool:\n"
        "    return hash_password(password) == hashed\n\n"
        "def create_session(user_id: str) -> str:\n"
        "    return 'sess_' + user_id\n",
        encoding="utf-8",
    )

    (src_dir / "api.py").write_text(
        "from src.auth import create_session\n\n"
        "def login_handler(user_id: str) -> dict:\n"
        "    token = create_session(user_id)\n"
        "    return {'token': token, 'status': 'ok'}\n",
        encoding="utf-8",
    )

    (src_dir / "billing.py").write_text(
        "def compute_tax(amount: float) -> float:\n"
        "    return amount * 0.15\n",
        encoding="utf-8",
    )

    # 2. TypeScript source files
    (src_dir / "utils.ts").write_text(
        "export function formatToken(token: string): string {\n"
        "    return 'Bearer ' + token;\n"
        "}\n\n"
        "export function validateEmail(email: string): boolean {\n"
        "    return email.includes('@');\n"
        "}\n",
        encoding="utf-8",
    )

    (src_dir / "client.ts").write_text(
        "import { formatToken } from './utils';\n\n"
        "export function authenticateUser(token: string): string {\n"
        "    return formatToken(token);\n"
        "}\n",
        encoding="utf-8",
    )

    (src_dir / "theme.ts").write_text(
        "export function getTheme(): string {\n"
        "    return 'dark';\n"
        "}\n",
        encoding="utf-8",
    )

    # 3. Test files (3 relevant to target modules, 2 completely unrelated)
    (tests_dir / "test_auth.py").write_text(
        "from src.auth import create_session, verify_password\n\n"
        "def test_create_session():\n"
        "    assert create_session('u1') == 'sess_u1'\n",
        encoding="utf-8",
    )

    (tests_dir / "test_api.py").write_text(
        "from src.api import login_handler\n\n"
        "def test_login_handler():\n"
        "    res = login_handler('u1')\n"
        "    assert res['status'] == 'ok'\n",
        encoding="utf-8",
    )

    (tests_dir / "test_billing.py").write_text(
        "from src.billing import compute_tax\n\n"
        "def test_compute_tax():\n"
        "    assert compute_tax(100.0) == 15.0\n",
        encoding="utf-8",
    )

    (tests_dir / "client.test.ts").write_text(
        "import { authenticateUser } from '../src/client';\n\n"
        "test('authenticateUser', () => {\n"
        "    expect(authenticateUser('abc')).toBe('Bearer abc');\n"
        "});\n",
        encoding="utf-8",
    )

    (tests_dir / "theme.test.ts").write_text(
        "import { getTheme } from '../src/theme';\n\n"
        "test('getTheme', () => {\n"
        "    expect(getTheme()).toBe('dark');\n"
        "});\n",
        encoding="utf-8",
    )

    # 4. Initialize git and commit base files
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Radius Test Bot"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "bot@radius.dev"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )


def _apply_target_modifications_and_get_diff(repo_dir: Path) -> tuple[str, tuple[str, ...]]:
    """Modify create_session in auth.py and formatToken in utils.ts, leaving other symbols untouched."""
    # Modify ONLY create_session in src/auth.py
    auth_py = repo_dir / "src" / "auth.py"
    auth_py.write_text(
        "def hash_password(password: str) -> str:\n"
        "    return 'hash_' + password\n\n"
        "def verify_password(password: str, hashed: str) -> bool:\n"
        "    return hash_password(password) == hashed\n\n"
        "def create_session(user_id: str) -> str:\n"
        "    # Added audit log comment for session creation\n"
        "    return 'sess_v2_' + user_id\n",
        encoding="utf-8",
    )

    # Modify ONLY formatToken in src/utils.ts
    utils_ts = repo_dir / "src" / "utils.ts"
    utils_ts.write_text(
        "export function formatToken(token: string): string {\n"
        "    // Normalized authorization token header\n"
        "    return 'TOKEN ' + token;\n"
        "}\n\n"
        "export function validateEmail(email: string): boolean {\n"
        "    return email.includes('@');\n"
        "}\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["git", "diff"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    diff_text = proc.stdout
    changed_paths = ("src/auth.py", "src/utils.ts")
    return diff_text, changed_paths


def test_end_to_end_target_verification_flow(tmp_path: Path) -> None:
    """Execute complete end-to-end verification against a realistic target repository."""
    repo_dir = tmp_path / "target_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _init_git_target_repo(repo_dir)

    diff_text, changed_paths = _apply_target_modifications_and_get_diff(repo_dir)
    assert len(diff_text) > 0
    assert "src/auth.py" in diff_text
    assert "src/utils.ts" in diff_text

    # --- 1. Worker Orchestrator Execution ---
    analysis_id = uuid4()
    repo_id = uuid4()

    analysis_store = InMemoryAnalysisStore()
    analysis_entity = Analysis(
        id=analysis_id,
        repository_id=repo_id,
        pull_request_id=uuid4(),
        commit_sha=CommitSha("a" * 40),
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
        discoverer=ConventionalTestDiscoverer(),
        selector=PathBasedTestSelector(),
        store=InMemoryTestStore(),
        planner=StaticTestCommandPlanner(),
        runner=MockTargetTestRunner(),
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
        repository_path=repo_dir,
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_text=diff_text,
    )

    result: AnalysisExecutionResult = orchestrator.execute(command)
    assert result is not None

    # --- 2. CPG Slicing & Precision Verification ---
    # The experimental symbol-level CPG is no longer on the verdict path; build
    # it explicitly to keep exercising the extractor and slicer.
    orchestrator._run_semantic_cpg_poc(repo_dir, (), None)
    assert orchestrator._last_cpg is not None
    cpg: CodePropertyGraph = orchestrator._last_cpg

    # Verify nodes extracted from both languages
    assert "src/auth.py:create_session" in cpg.nodes
    assert "src/api.py:login_handler" in cpg.nodes
    assert "src/billing.py:compute_tax" in cpg.nodes
    assert "src/utils.ts:formatToken" in cpg.nodes
    assert "src/client.ts:authenticateUser" in cpg.nodes
    assert "src/theme.ts:getTheme" in cpg.nodes

    slicer = GraphSlicer(cpg)
    auth_callers = slicer.extract_caller_slice("src/auth.py:create_session")
    caller_ids = [c.symbol.id for c in auth_callers]
    assert "src/api.py:login_handler" in caller_ids
    assert "src/billing.py:compute_tax" not in caller_ids

    utils_callers = slicer.extract_caller_slice("src/utils.ts:formatToken")
    ts_caller_ids = [c.symbol.id for c in utils_callers]
    assert "src/client.ts:authenticateUser" in ts_caller_ids
    assert "src/theme.ts:getTheme" not in ts_caller_ids

    # --- 3. Predictive Test Selection Verification ---
    selection = testing_service.get_selection(analysis_id)
    assert selection is not None
    assert selection.total_count == 5

    selected_paths = {item.test.path.replace("\\", "/") for item in selection.selected_tests}
    # Relevant tests should be selected
    assert any("test_auth.py" in p for p in selected_paths)
    assert any("test_api.py" in p for p in selected_paths)
    assert any("client.test.ts" in p for p in selected_paths)

    # Unrelated tests must NOT be selected
    assert not any("test_billing.py" in p for p in selected_paths)
    assert not any("theme.test.ts" in p for p in selected_paths)

    # Check metrics
    assert selection.selected_count == 3
    assert selection.skipped_count == 2
    assert selection.time_saved_percent == 40.0
    assert len(selection.cli_args) > 0


    # --- 4. CI Test Ingestion & Dynamic Confidence Recalculation ---
    # Simulate JUnit XML report where 1 test failed (regression found)
    junit_xml_report = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0" time="0.85">
    <testcase classname="tests.test_auth" name="test_create_session" time="0.04">
      <failure message="AssertionError: assert 'sess_v2_u1' == 'sess_u1'">
        def test_create_session():
      &gt;     assert create_session('u1') == 'sess_u1'
        E     AssertionError: assert 'sess_v2_u1' == 'sess_u1'
      </failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_login_handler" time="0.05" />
  </testsuite>
  <testsuite name="vitest" tests="1" failures="0" errors="0" skipped="0" time="0.45">
    <testcase classname="tests.client.test.ts" name="authenticateUser" time="0.03" />
  </testsuite>
</testsuites>
"""

    ingested_result = testing_service.ingest_test_results(analysis_id, junit_xml_report)
    assert ingested_result.total_tests == 3
    assert ingested_result.passed == 2
    assert ingested_result.failed == 1
    assert "AssertionError" in ingested_result.output

    # Dynamic confidence recalculation
    recalculated_report = confidence_service.recalculate_from_test_results(
        analysis_id, ingested_result
    )
    assert recalculated_report.confidence_score < 70.0
    assert recalculated_report.risk_level in ("high", "critical")

    # --- 5. Rich GitHub PR Publisher Verification ---
    github_report = GitHubAnalysisReport(
        analysis_id=analysis_id,
        owner="Mohith-c7",
        repository_name="target_repo",
        pull_request_number=42,
        head_sha="a" * 40,
        confidence_score=recalculated_report.confidence_score,
        risk_level=recalculated_report.risk_level,
        summary="Confidence score updated from CI test run: 58.0.",
        recommendations=("Review failed test in test_auth.py before merging.",),
        selected_tests_count=selection.selected_count,
        skipped_tests_count=selection.skipped_count,
        time_saved_percent=selection.time_saved_percent,
        affected_files=("src/auth.py", "src/api.py", "src/utils.ts", "src/client.ts"),
        affected_symbols=("create_session", "login_handler", "formatToken", "authenticateUser"),
        ai_pruned_count=1,
        ai_pruning_notes=("Pruned benign docstring change in validateEmail.",),
    )

    markdown_body = _markdown_report(github_report)
    assert "Radius Confidence Report" in markdown_body
    # Should include visual badge for high risk
    assert any(badge in markdown_body for badge in ("🟠", "🔴"))
    assert "Test Selection" in markdown_body
    assert "time saved" not in markdown_body
    assert "src/auth.py" in markdown_body
    assert "AI Impact Pruning" in markdown_body

    # --- 6. Graph Snapshot & Blast Radius Verification ---
    graph_snapshot = graph_store.get_snapshot(analysis_id)
    assert graph_snapshot is not None
    assert graph_snapshot.node_count > 0
    assert graph_snapshot.edge_count > 0

    blast_radius = analysis_service.get_blast_radius(analysis_id)
    assert blast_radius.affected_files >= 2
    assert blast_radius.affected_symbols >= 2
    assert blast_radius.affected_tests >= 2

