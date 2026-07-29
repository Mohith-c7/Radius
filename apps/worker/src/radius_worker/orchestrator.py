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
        self._testing.discover_tests(DiscoverTestsCommand(command.repository_path))
        selection = self._testing.select_tests(
            SelectTestsCommand(
                analysis_id=command.analysis_id,
                changed_file_paths=changed_paths,
                affected_file_paths=affected_paths,
            )
        )
        self._testing.plan_test_run(PlanTestRunCommand(command.analysis_id))
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
                    total_tests=selection.selected_count,
                    passed=selection.selected_count,
                    failed=0,
                    skipped=0,
                    coverage_percent=CoveragePercent(0),
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
