"""Phase 1 deterministic analysis orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import (
    AnalyzeDiffCommand,
    AnalyzeRepositoryDiffCommand,
    ComputeBlastRadiusCommand,
)
from radius_analysis.symbol_impact import refine_dependents
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import (
    AnalysisEvidence,
    CoveragePercent,
    ImpactEvidence,
    TestEvidence,
    TestRunOutcome,
)
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_graph.application import GraphApplicationService
from radius_graph.domain import GraphSnapshot
from radius_graph.dto import BuildGraphCommand
from radius_graph.interfaces.graph_store import GraphStore
from radius_graph.traversal import file_dependents
from radius_parser.application import ParserApplicationService
from radius_parser.dto import ParseRepositoryCommand
from radius_parser.extractors.typescript import TypeScriptExtractor
from radius_shared.logging import get_logger
from radius_shared.observability import stage
from radius_testing.application import TestingApplicationService
from radius_testing.dto import (
    DiscoverTestsCommand,
    ExecuteTestRunCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)
from radius_testing.infrastructure.impact_mapping import (
    ChangedFileRef,
    map_changes_to_tests,
)
from radius_testing.infrastructure.selection import PathBasedTestSelector

LOGGER = get_logger(__name__)


_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}
)


def _read_python_sources(root: Path) -> dict[str, str]:
    """Read repository ``.py`` files (no symlink escapes) keyed by posix path."""

    sources: dict[str, str] = {}
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts) or path.is_symlink():
            continue
        try:
            if resolved_root not in path.resolve().parents:
                continue
            sources[rel.as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return sources


@dataclass(frozen=True, slots=True)
class ExecuteAnalysisCommand:
    """Worker command for one deterministic Phase 1 analysis run."""

    analysis_id: UUID
    repository_id: UUID
    repository_path: Path
    diff_text: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisExecutionResult:
    """Summary of artifacts produced by a worker analysis run."""

    analysis_id: UUID
    changed_file_count: int
    graph_node_count: int
    graph_edge_count: int
    affected_files: int
    selected_tests: int
    confidence_score: float
    risk_level: str
    verification_status: str = "insufficient_evidence"


class Phase1AnalysisOrchestrator:
    """Run the deterministic Phase 1 backend pipeline."""

    def __init__(
        self,
        analysis_service: AnalysisApplicationService,
        parser_service: ParserApplicationService,
        graph_service: GraphApplicationService,
        graph_store: GraphStore,
        testing_service: TestingApplicationService,
        confidence_service: ConfidenceApplicationService,
        execute_tests: bool = True,
        symbol_impact_enabled: bool = False,
    ) -> None:
        self._analysis = analysis_service
        self._parser = parser_service
        self._graph = graph_service
        self._graph_store = graph_store
        self._testing = testing_service
        self._confidence = confidence_service
        self._execute_tests = execute_tests
        self._symbol_impact_enabled = symbol_impact_enabled

    def execute(self, command: ExecuteAnalysisCommand) -> AnalysisExecutionResult:
        """Execute one analysis and mark its lifecycle status."""

        self._analysis.mark_running(command.analysis_id)
        try:
            result = self._execute(command)
        except Exception:
            self._analysis.fail_analysis(command.analysis_id)
            raise
        self._analysis.complete_analysis(command.analysis_id)
        return result

    def _execute(self, command: ExecuteAnalysisCommand) -> AnalysisExecutionResult:
        with stage("analyze_changes"):
            changes = self._analyze_changes(command)
        changed_paths = tuple(item.path for item in changes.changed_files)

        # NOTE: the experimental LLM "semantic pruning" step is intentionally
        # NOT part of this pipeline. It could remove files (and therefore
        # tests) from the blast radius based on an unvalidated model judgment,
        # which is a false-safety risk. See docs/audit/RADIUS_AUDIT.md.

        with stage("parse"):
            parse_result = self._parser.parse_repository_result(
                ParseRepositoryCommand(repository_path=command.repository_path)
            )
        if parse_result.parse_failures:
            LOGGER.warning(
                "Some source files could not be parsed",
                extra={
                    "analysis_id": str(command.analysis_id),
                    "parse_failures": len(parse_result.parse_failures),
                },
            )
        with stage("build_graph"):
            graph_response = self._graph.build_graph(
                BuildGraphCommand(
                    repository_id=command.repository_id,
                    analysis_id=command.analysis_id,
                    parse_result=parse_result,
                )
            )
        graph_snapshot = self._require_graph_snapshot(command.analysis_id)
        dependents = file_dependents(graph_snapshot.graph, changed_paths)
        with stage("discover_tests"):
            discovered_tests = self._testing.discover_test_cases(
                DiscoverTestsCommand(command.repository_path, command.repository_id)
            )
        symbol_evidence: dict[str, tuple[str, ...]] | None = None
        changed_symbols: tuple[str, ...] = ()
        symbol_scope: tuple[str, ...] | None = None
        if self._symbol_impact_enabled:
            refined = self._refine_with_symbols(
                command, changes, changed_paths, dependents, discovered_tests,
                graph_snapshot,
            )
            if refined is not None:
                dependents = refined.dependents
                symbol_evidence = refined.test_evidence
                changed_symbols = refined.changed_symbols
                symbol_scope = tuple(
                    sorted({p for reached in dependents.values() for p in reached})
                )
        affected_paths = tuple(
            sorted(
                {path for reached in dependents.values() for path in reached}
                - set(changed_paths)
            )
        )

        selector = PathBasedTestSelector()
        mapping = map_changes_to_tests(
            changed_files=tuple(
                ChangedFileRef(item.path, item.change_type)
                for item in changes.changed_files
            ),
            dependents=dependents,
            test_paths=frozenset(test.path.value for test in discovered_tests),
            conventional_tests={
                path: selector.conventional_matches(path, discovered_tests)
                for path in changed_paths
            },
            parse_failures=frozenset(parse_result.parse_failures),
        )
        with stage("select_tests"):
            selection = self._testing.select_tests(
                SelectTestsCommand(
                    analysis_id=command.analysis_id,
                    changed_file_paths=changed_paths,
                    affected_file_paths=affected_paths,
                    available_tests=discovered_tests,
                    full_suite_reasons=mapping.full_suite_reasons,
                    changed_symbols=changed_symbols,
                    symbol_evidence=symbol_evidence,
                )
            )
        self._testing.plan_test_run(PlanTestRunCommand(command.analysis_id))
        with stage("run_tests"):
            test_evidence = self._run_or_defer_tests(command, selection.selected_count)

        with stage("blast_radius"):
            blast_radius = self._analysis.compute_blast_radius(
                ComputeBlastRadiusCommand(
                    analysis_id=command.analysis_id,
                    graph_snapshot=graph_snapshot,
                    changed_file_paths=changed_paths,
                    affected_test_paths=tuple(
                        item.test.path for item in selection.selected_tests
                    ),
                    symbol_affected_file_paths=symbol_scope,
                )
            )
        with stage("confidence"):
            confidence = self._confidence.generate_report(
                GenerateConfidenceReportCommand(
                    analysis_id=command.analysis_id,
                    impact=ImpactEvidence(
                        affected_files=blast_radius.affected_files,
                        affected_symbols=blast_radius.affected_symbols,
                        affected_modules=blast_radius.affected_modules,
                        affected_tests=blast_radius.affected_tests,
                        dependency_depth=blast_radius.dependency_depth,
                    ),
                    tests=test_evidence,
                    analysis=AnalysisEvidence(
                        changed_files=len(changed_paths),
                        covered_files=mapping.covered_files,
                        unmapped_files=mapping.unmapped_files,
                        unanalyzed_files=mapping.unanalyzed_files,
                        non_executable_files=mapping.non_executable_files,
                        parse_failures=mapping.parse_failures,
                        full_suite_fallback_reasons=mapping.full_suite_reasons,
                    ),
                ),
            )
        LOGGER.info(
            "Analysis completed",
            extra={
                "analysis_id": str(command.analysis_id),
                "selected_tests": selection.selected_count,
                "discovered_tests": selection.total_count,
                "verification_status": confidence.verification_status,
            },
        )
        return AnalysisExecutionResult(
            analysis_id=command.analysis_id,
            changed_file_count=len(changes.changed_files),
            graph_node_count=graph_response.node_count,
            graph_edge_count=graph_response.edge_count,
            affected_files=blast_radius.affected_files,
            selected_tests=selection.selected_count,
            confidence_score=confidence.confidence_score,
            risk_level=confidence.risk_level,
            verification_status=confidence.verification_status,
        )

    def _refine_with_symbols(
        self,
        command: ExecuteAnalysisCommand,
        changes,
        changed_paths: tuple[str, ...],
        dependents: dict[str, frozenset[str]],
        discovered_tests,
        graph_snapshot: GraphSnapshot,
    ):
        """Symbol-level refinement (F-08); ``None`` keeps the file-level result."""

        diff_text = command.diff_text or getattr(changes, "diff_text", None)
        try:
            refined = refine_dependents(
                diff_text=diff_text,
                changed_paths=changed_paths,
                file_level=dependents,
                python_sources=_read_python_sources(command.repository_path),
                test_paths=frozenset(test.path.value for test in discovered_tests),
                graph=graph_snapshot.graph,
            )
        except Exception:  # never let an optimisation break the safe path
            LOGGER.warning(
                "Symbol-level impact failed; using file-level impact",
                extra={"analysis_id": str(command.analysis_id)},
                exc_info=True,
            )
            return None
        LOGGER.info(
            "Symbol-level impact computed",
            extra={
                "analysis_id": str(command.analysis_id),
                "algo_version": refined.algo_version,
                "file_level_fallbacks": len(refined.fallbacks),
                "changed_symbols": len(refined.changed_symbols),
            },
        )
        return refined

    def _run_or_defer_tests(
        self,
        command: ExecuteAnalysisCommand,
        selected_count: int,
    ) -> TestEvidence:
        if not self._execute_tests:
            return TestEvidence(
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                run_outcome=TestRunOutcome.NOT_RUN,
                run_detail="in-worker test execution is disabled",
            )
        if selected_count == 0:
            return TestEvidence(total_tests=0, passed=0, failed=0, skipped=0)
        result = self._testing.execute_test_run(
            ExecuteTestRunCommand(
                analysis_id=command.analysis_id,
                repository_path=command.repository_path,
            )
        )
        outcome = (
            TestRunOutcome.ERROR
            if result.status == "error"
            else TestRunOutcome.COMPLETED
        )
        return TestEvidence(
            total_tests=result.total_tests,
            passed=result.passed,
            failed=result.failed,
            skipped=result.skipped,
            coverage_percent=(
                CoveragePercent(result.coverage_percent)
                if result.coverage_percent is not None
                else None
            ),
            run_outcome=outcome,
            run_detail=(result.output.splitlines()[0][:200] if outcome != TestRunOutcome.COMPLETED and result.output else None),
        )

    def _run_semantic_cpg_poc(
        self, repo_path: Path, changed_paths: tuple[str, ...], diff_text: str | None
    ) -> set[str]:
        import os

        from radius_analysis.ai.pruner import SemanticPruner
        from radius_analysis.diff_hunks import parse_diff_modified_lines
        from radius_graph.cpg import CodePropertyGraph
        from radius_graph.slicer import GraphSlicer
        from radius_parser.core import ParserEngine
        from radius_parser.extractors.python import PythonExtractor

        print(
            f"\n[PHASE 2 POC] Starting Semantic CPG Engine on cloned repo: {repo_path}"
        )
        engine = ParserEngine()
        py_extractor = PythonExtractor()
        ts_extractor = TypeScriptExtractor()
        cpg = CodePropertyGraph()

        py_extensions = (".py",)
        ts_extensions = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

        # 1. Parse all files dynamically
        ignored_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".turbo"}
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                is_py = file.endswith(py_extensions)
                is_ts = file.endswith(ts_extensions)
                if not (is_py or is_ts):
                    continue

                filepath = os.path.join(root, file)

                # [SECURITY] Mitigate Symlink Traversal / Arbitrary File Read
                resolved_path = os.path.realpath(filepath)
                resolved_repo = os.path.realpath(repo_path)
                if not resolved_path.startswith(resolved_repo):
                    print(
                        f"[SECURITY WARNING] Blocked arbitrary file read attempt via symlink: {filepath}"
                    )
                    continue

                try:
                    with open(filepath, encoding="utf-8") as f:
                        code = f.read()
                    rel_path = os.path.relpath(filepath, repo_path).replace("\\", "/")
                    if is_py:
                        tree = engine.parse_python(code)
                        for imp in py_extractor.extract_imports(
                            tree.root_node, rel_path, code
                        ):
                            cpg.add_import(imp)
                        symbols = py_extractor.extract_symbols(
                            tree.root_node, rel_path, code
                        )
                        for sym in symbols:
                            cpg.add_symbol(sym)
                            sym_tree = engine.parse_python(sym.source_code)
                            calls = py_extractor.extract_calls(
                                sym_tree.root_node, sym.id, sym.source_code
                            )
                            for call in calls:
                                cpg.add_reference(call)
                    elif is_ts:
                        tree = engine.parse_typescript(code)
                        for imp in ts_extractor.extract_imports(
                            tree.root_node, rel_path, code
                        ):
                            cpg.add_import(imp)
                        symbols = ts_extractor.extract_symbols(
                            tree.root_node, rel_path, code
                        )
                        for sym in symbols:
                            cpg.add_symbol(sym)
                            sym_tree = engine.parse_typescript(sym.source_code)
                            calls = ts_extractor.extract_calls(
                                sym_tree.root_node, sym.id, sym.source_code
                            )
                            for call in calls:
                                cpg.add_reference(call)

                except Exception:
                    pass

        print(f"[PHASE 2 POC] CPG Built successfully. Total Nodes: {len(cpg.nodes)}")
        self._last_cpg = cpg

        slicer = GraphSlicer(cpg)
        api_key = os.environ.get("GEMINI_API_KEY", "")
        pruner = SemanticPruner(api_key=api_key)

        pruned_files = set()
        modified_lines_by_file = (
            parse_diff_modified_lines(diff_text) if diff_text else {}
        )

        # 2. Extract Blast Radius for changes
        for path in changed_paths:
            path_norm = path.replace("\\", "/")
            if not path_norm.endswith(
                (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
            ):
                continue

            print(f"[PHASE 2 POC] Analyzing changed file: {path_norm}")
            for node_id, node in cpg.nodes.items():
                if node.symbol.file_path == path_norm:
                    if (
                        path_norm in modified_lines_by_file
                        and modified_lines_by_file[path_norm]
                    ):
                        mod_lines = modified_lines_by_file[path_norm]
                        sym = node.symbol
                        overlaps = any(
                            sym.start_line <= line <= sym.end_line for line in mod_lines
                        )
                        if not overlaps:
                            print(
                                f"[PHASE 2 POC] Skipping untouched symbol '{node_id}' ({sym.start_line}-{sym.end_line})"
                            )
                            continue

                    slice_nodes = slicer.extract_caller_slice(node_id)
                    if slice_nodes:
                        print(
                            f"[PHASE 2 POC] Target '{node_id}' has {len(slice_nodes)} dependent callers."
                        )
                        for caller in slice_nodes:
                            if api_key:
                                is_impacted = pruner.evaluate_impact(
                                    caller.symbol.source_code, str(diff_text)
                                )
                                if not is_impacted:
                                    print(
                                        f"[PHASE 2 POC] -> Caller {caller.symbol.id}: PRUNE (Benign)"
                                    )
                                    pruned_files.add(caller.symbol.file_path)
                                else:
                                    print(
                                        f"[PHASE 2 POC] -> Caller {caller.symbol.id}: KEEP (Breaking)"
                                    )
                            else:
                                print(
                                    f"[PHASE 2 POC] -> Caller {caller.symbol.id}: Skipped AI Eval (No API Key)"
                                )

        return pruned_files

    def _analyze_changes(self, command: ExecuteAnalysisCommand):
        if command.diff_text is not None:
            return self._analysis.analyze_diff(
                AnalyzeDiffCommand(
                    analysis_id=command.analysis_id,
                    diff_text=command.diff_text,
                )
            )
        if command.base_ref is None or command.head_ref is None:
            msg = "Either diff_text or both base_ref and head_ref are required."
            raise ValueError(msg)
        return self._analysis.analyze_repository_diff(
            AnalyzeRepositoryDiffCommand(
                analysis_id=command.analysis_id,
                repository_path=str(command.repository_path),
                base_ref=command.base_ref,
                head_ref=command.head_ref,
            )
        )

    def _require_graph_snapshot(self, analysis_id: UUID) -> GraphSnapshot:
        snapshot = self._graph_store.get_snapshot(analysis_id)
        if snapshot is None:
            msg = f"Graph snapshot for analysis {analysis_id} was not found."
            raise ValueError(msg)
        return snapshot
