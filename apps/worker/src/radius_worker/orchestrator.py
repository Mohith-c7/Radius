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
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import CoveragePercent, ImpactEvidence, TestEvidence
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_graph.application import GraphApplicationService
from radius_graph.domain import GraphEdgeType, GraphNodeId, GraphNodeType, GraphSnapshot
from radius_graph.dto import BuildGraphCommand
from radius_graph.interfaces.graph_store import GraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.dto import ParseRepositoryCommand
from radius_testing.application import TestingApplicationService
from radius_testing.dto import (
    DiscoverTestsCommand,
    ExecuteTestRunCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)


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
    ) -> None:
        self._analysis = analysis_service
        self._parser = parser_service
        self._graph = graph_service
        self._graph_store = graph_store
        self._testing = testing_service
        self._confidence = confidence_service

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
        changes = self._analyze_changes(command)
        changed_paths = tuple(item.path for item in changes.changed_files)
        
        # --- PHASE 2 POC INTEGRATION ---
        pruned_files = set()
        try:
            pruned_files = self._run_semantic_cpg_poc(command.repository_path, changed_paths, command.diff_text)
        except Exception as e:
            print(f"[PHASE 2 POC] Error running semantic cpg pipeline: {e}")
            
        parse_result = self._parser.parse_repository_result(
            ParseRepositoryCommand(repository_path=command.repository_path)
        )
        graph_response = self._graph.build_graph(
            BuildGraphCommand(
                repository_id=command.repository_id,
                analysis_id=command.analysis_id,
                parse_result=parse_result,
            )
        )
        graph_snapshot = self._require_graph_snapshot(command.analysis_id)
        affected_paths = self._affected_file_paths(graph_snapshot, changed_paths)
        
        # [NEW] Actually apply the AI pruning to the pipeline so the UI receives the filtered results!
        if pruned_files:
            affected_paths = tuple(p for p in affected_paths if p.replace("\\", "/") not in pruned_files)
            
        self._testing.discover_tests(DiscoverTestsCommand(command.repository_path))
        selection = self._testing.select_tests(
            SelectTestsCommand(
                analysis_id=command.analysis_id,
                changed_file_paths=changed_paths,
                affected_file_paths=affected_paths,
            )
        )
        self._testing.plan_test_run(PlanTestRunCommand(command.analysis_id))
        test_result = self._testing.execute_test_run(
            ExecuteTestRunCommand(
                analysis_id=command.analysis_id,
                repository_path=command.repository_path,
            )
        )
        blast_radius = self._analysis.compute_blast_radius(
            ComputeBlastRadiusCommand(
                analysis_id=command.analysis_id,
                graph_snapshot=graph_snapshot,
                changed_file_paths=changed_paths,
                affected_test_paths=tuple(
                    item.test.path for item in selection.selected_tests
                ),
            )
        )
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
                tests=TestEvidence(
                    total_tests=test_result.total_tests,
                    passed=test_result.passed,
                    failed=test_result.failed,
                    skipped=test_result.skipped,
                    coverage_percent=(
                        CoveragePercent(test_result.coverage_percent)
                        if test_result.coverage_percent is not None
                        else None
                    ),
                ),
            )
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
        )

    def _run_semantic_cpg_poc(self, repo_path: Path, changed_paths: tuple[str, ...], diff_text: str | None) -> set[str]:
        import os
        from radius_parser.core import ParserEngine
        from radius_parser.extractors.python import PythonExtractor
        from radius_graph.cpg import CodePropertyGraph
        from radius_graph.slicer import GraphSlicer
        from radius_analysis.ai.pruner import SemanticPruner
        
        print(f"\n[PHASE 2 POC] Starting Semantic CPG Engine on cloned repo: {repo_path}")
        engine = ParserEngine()
        extractor = PythonExtractor()
        cpg = CodePropertyGraph()
        
        # 1. Parse all python files dynamically
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            code = f.read()
                        tree = engine.parse_python(code)
                        # Ensure rel_path matches standard path format
                        rel_path = os.path.relpath(filepath, repo_path).replace("\\", "/")
                        symbols = extractor.extract_symbols(tree.root_node, rel_path, code)
                        for sym in symbols:
                            cpg.add_symbol(sym)
                            sym_tree = engine.parse_python(sym.source_code)
                            calls = extractor.extract_calls(sym_tree.root_node, sym.id, sym.source_code)
                            for call in calls:
                                cpg.add_reference(call)
                    except Exception:
                        pass
                        
        print(f"[PHASE 2 POC] CPG Built successfully. Total Nodes: {len(cpg.nodes)}")
        
        slicer = GraphSlicer(cpg)
        api_key = os.environ.get("GEMINI_API_KEY", "")
        pruner = SemanticPruner(api_key=api_key)
        
        pruned_files = set()
        
        # 2. Extract Blast Radius for changes
        for path in changed_paths:
            path_norm = path.replace("\\", "/")
            if not path_norm.endswith(".py"): 
                continue
            
            print(f"[PHASE 2 POC] Analyzing changed file: {path_norm}")
            for node_id, node in cpg.nodes.items():
                if node.symbol.file_path == path_norm:
                    slice_nodes = slicer.extract_caller_slice(node_id)
                    if slice_nodes:
                        print(f"[PHASE 2 POC] Target '{node_id}' has {len(slice_nodes)} dependent callers.")
                        for caller in slice_nodes:
                            if api_key:
                                is_impacted = pruner.evaluate_impact(caller.symbol.source_code, str(diff_text))
                                if not is_impacted:
                                    print(f"[PHASE 2 POC] -> Caller {caller.symbol.id}: PRUNE (Benign)")
                                    pruned_files.add(caller.symbol.file_path)
                                else:
                                    print(f"[PHASE 2 POC] -> Caller {caller.symbol.id}: KEEP (Breaking)")
                            else:
                                print(f"[PHASE 2 POC] -> Caller {caller.symbol.id}: Skipped AI Eval (No API Key)")
                                
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

    @staticmethod
    def _affected_file_paths(
        graph_snapshot: GraphSnapshot,
        changed_paths: tuple[str, ...],
    ) -> tuple[str, ...]:
        start_ids = {GraphNodeId(f"file:{path}") for path in changed_paths}
        graph_node_ids = graph_snapshot.graph.node_ids()
        affected = {node_id for node_id in start_ids if node_id in graph_node_ids}
        frontier = set(affected)
        while frontier:
            next_frontier: set[GraphNodeId] = set()
            for edge in graph_snapshot.graph.edges:
                if (
                    edge.edge_type == GraphEdgeType.DEPENDS_ON
                    and edge.target_id in frontier
                    and edge.source_id not in affected
                ):
                    affected.add(edge.source_id)
                    next_frontier.add(edge.source_id)
            frontier = next_frontier
        paths = {
            node.path
            for node in graph_snapshot.graph.nodes
            if node.id in affected
            and node.node_type == GraphNodeType.FILE
            and node.path is not None
        }
        return tuple(sorted(paths - set(changed_paths)))
