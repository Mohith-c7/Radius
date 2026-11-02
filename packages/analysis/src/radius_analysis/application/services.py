"""Analysis application service."""

from pathlib import Path
from uuid import UUID

from radius_graph.domain.entities import GraphEdge, GraphSnapshot
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId
from radius_shared.errors import NotFoundError, ValidationError

from radius_analysis.domain.entities import Analysis, BlastRadius, ChangedFile
from radius_analysis.domain.enums import AnalysisStatus, ChangedFileType
from radius_analysis.domain.value_objects import CommitSha, FilePath
from radius_analysis.dto.commands import (
    AnalysisListQuery,
    AnalyzeDiffCommand,
    AnalyzeRepositoryDiffCommand,
    ComputeBlastRadiusCommand,
    RecordChangedFilesCommand,
    RerunAnalysisCommand,
    SaveBlastRadiusCommand,
    StartAnalysisCommand,
)
from radius_analysis.dto.responses import (
    AnalysisDetailResponse,
    AnalysisResponse,
    BlastRadiusResponse,
    ChangeAnalysisResponse,
    ChangedFileResponse,
)
from radius_analysis.interfaces.analysis_store import AnalysisStore
from radius_analysis.interfaces.change_analyzer import (
    GitChangeAnalyzer,
    GitDiffProvider,
)
from radius_analysis.interfaces.pipeline import AnalysisPipeline


class AnalysisApplicationService:
    """Coordinates Phase 1 analysis lifecycle use cases."""

    def __init__(
        self,
        store: AnalysisStore,
        pipeline: AnalysisPipeline | None = None,
        change_analyzer: GitChangeAnalyzer | None = None,
        diff_provider: GitDiffProvider | None = None,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
        self._change_analyzer = change_analyzer
        self._diff_provider = diff_provider

    def start_analysis(
        self,
        command: StartAnalysisCommand,
        *,
        force: bool = False,
    ) -> AnalysisDetailResponse:
        """Create a new analysis run and optionally enqueue processing.

        Webhook redeliveries and overlapping PR events (``opened`` then
        ``ready_for_review``) for the same head commit reuse the pending or
        running analysis instead of enqueuing duplicate work. ``force``
        bypasses this for explicit re-runs.
        """

        if not force:
            find_active = getattr(self._store, "find_active", None)
            existing = (
                find_active(command.pull_request_id, command.commit_sha)
                if find_active is not None
                else None
            )
            if existing is not None:
                return AnalysisDetailResponse.from_entity(existing)

        analysis = Analysis(
            id=None,
            repository_id=command.repository_id,
            pull_request_id=command.pull_request_id,
            commit_sha=CommitSha(command.commit_sha),
            status=AnalysisStatus.PENDING,
        )
        saved = self._store.save(analysis)
        if saved.id is not None and self._pipeline is not None:
            self._pipeline.enqueue(saved.id)
        return AnalysisDetailResponse.from_entity(saved)

    def rerun_analysis(
        self,
        command: RerunAnalysisCommand,
    ) -> AnalysisDetailResponse:
        """Create a brand-new analysis from an existing analysis context."""

        existing = self._get_required(command.analysis_id)
        return self.start_analysis(
            StartAnalysisCommand(
                repository_id=existing.repository_id,
                pull_request_id=existing.pull_request_id,
                commit_sha=existing.commit_sha.value,
            ),
            force=True,
        )

    def cancel_queued(
        self,
        *,
        reason: str,
        pull_request_id: UUID | None = None,
        repository_id: UUID | None = None,
    ) -> list[UUID]:
        """Cancel analyses that are queued but have not started.

        Only ``pending`` analyses whose job the queue confirms was never
        started are cancelled; a running analysis is never touched. Returns the
        cancelled analysis ids.
        """

        if pull_request_id is None and repository_id is None:
            msg = "cancel_queued needs a pull request or repository scope."
            raise ValidationError(msg)
        cancel_job = getattr(self._pipeline, "cancel_queued", None)
        cancelled: list[UUID] = []
        for analysis in self._store.list(
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            status=AnalysisStatus.PENDING,
        ):
            if analysis.id is None:
                continue
            if cancel_job is not None and not cancel_job(analysis.id, reason):
                continue
            analysis.cancel()
            self._store.update_status(analysis.id, analysis.status)
            cancelled.append(analysis.id)
        return cancelled

    def get_analysis(self, analysis_id: UUID) -> AnalysisDetailResponse:
        """Return an analysis summary with changed-file evidence."""

        return AnalysisDetailResponse.from_entity(self._get_required(analysis_id))

    def list_analyses(self, query: AnalysisListQuery) -> list[AnalysisResponse]:
        """List analyses with optional filters."""

        analyses = self._store.list(
            repository_id=query.repository_id,
            pull_request_id=query.pull_request_id,
            status=self._parse_status(query.status),
        )
        return [AnalysisResponse.from_entity(analysis) for analysis in analyses]

    def mark_running(self, analysis_id: UUID) -> AnalysisResponse:
        """Move an analysis into running state."""

        analysis = self._get_required(analysis_id)
        analysis.mark_running()
        saved = self._store.update_status(analysis_id, analysis.status)
        return AnalysisResponse.from_entity(saved)

    def complete_analysis(self, analysis_id: UUID) -> AnalysisResponse:
        """Mark an analysis completed."""

        analysis = self._get_required(analysis_id)
        analysis.complete()
        saved = self._store.update_status(analysis_id, analysis.status)
        return AnalysisResponse.from_entity(saved)

    def fail_analysis(self, analysis_id: UUID) -> AnalysisResponse:
        """Mark an analysis failed."""

        analysis = self._get_required(analysis_id)
        analysis.fail()
        saved = self._store.update_status(analysis_id, analysis.status)
        return AnalysisResponse.from_entity(saved)

    def cancel_analysis(self, analysis_id: UUID) -> AnalysisResponse:
        """Cancel an analysis."""

        analysis = self._get_required(analysis_id)
        analysis.cancel()
        saved = self._store.update_status(analysis_id, analysis.status)
        return AnalysisResponse.from_entity(saved)

    def record_changed_files(
        self,
        command: RecordChangedFilesCommand,
    ) -> tuple[ChangedFileResponse, ...]:
        """Replace changed-file evidence for an analysis."""

        if self._store.get_by_id(command.analysis_id) is None:
            msg = f"Analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)

        changed_files = [
            ChangedFile(
                id=None,
                analysis_id=command.analysis_id,
                path=FilePath(item.path),
                change_type=self._parse_change_type(item.change_type),
                additions=item.additions,
                deletions=item.deletions,
            )
            for item in command.changed_files
        ]
        saved = self._store.replace_changed_files(
            command.analysis_id,
            changed_files,
        )
        return tuple(ChangedFileResponse.from_entity(item) for item in saved)

    def analyze_diff(self, command: AnalyzeDiffCommand) -> ChangeAnalysisResponse:
        """Parse raw diff text and record changed-file evidence."""

        if self._change_analyzer is None:
            msg = "Git change analyzer is not configured."
            raise ValidationError(msg)

        changed_files = self._change_analyzer.analyze_diff(command.diff_text)
        responses = self.record_changed_files(
            RecordChangedFilesCommand(
                analysis_id=command.analysis_id,
                changed_files=changed_files,
            )
        )
        return ChangeAnalysisResponse(
            analysis_id=command.analysis_id,
            changed_files=responses,
            diff_text=command.diff_text,
        )

    def analyze_repository_diff(
        self,
        command: AnalyzeRepositoryDiffCommand,
    ) -> ChangeAnalysisResponse:
        """Collect a repository diff and record changed-file evidence."""

        if self._diff_provider is None:
            msg = "Git diff provider is not configured."
            raise ValidationError(msg)

        diff_text = self._diff_provider.get_diff(
            Path(command.repository_path),
            command.base_ref,
            command.head_ref,
        )
        return self.analyze_diff(
            AnalyzeDiffCommand(
                analysis_id=command.analysis_id,
                diff_text=diff_text,
            )
        )

    def save_blast_radius(
        self,
        command: SaveBlastRadiusCommand,
    ) -> BlastRadiusResponse:
        """Store deterministic impact-analysis summary."""

        if self._store.get_by_id(command.analysis_id) is None:
            msg = f"Analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)

        blast_radius = BlastRadius(
            id=None,
            analysis_id=command.analysis_id,
            affected_files=command.affected_files,
            affected_symbols=command.affected_symbols,
            affected_modules=command.affected_modules,
            affected_tests=command.affected_tests,
            dependency_depth=command.dependency_depth,
        )
        saved = self._store.save_blast_radius(blast_radius)
        return BlastRadiusResponse.from_entity(saved)

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadiusResponse:
        """Return deterministic impact-analysis summary."""

        if self._store.get_by_id(analysis_id) is None:
            msg = f"Analysis {analysis_id} was not found."
            raise NotFoundError(msg)

        blast_radius = self._store.get_blast_radius(analysis_id)
        if blast_radius is None:
            msg = f"Blast radius for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return BlastRadiusResponse.from_entity(blast_radius)

    def compute_blast_radius(
        self,
        command: ComputeBlastRadiusCommand,
    ) -> BlastRadiusResponse:
        """Compute and persist blast radius from graph reverse dependencies."""

        if self._store.get_by_id(command.analysis_id) is None:
            msg = f"Analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)

        affected_ids, dependency_depth = self._traverse_reverse_dependencies(
            command.graph_snapshot,
            {
                GraphNodeId(f"file:{self._normalize_graph_path(path)}")
                for path in command.changed_file_paths
            },
        )
        if command.symbol_affected_file_paths is not None:
            keep = {
                self._normalize_graph_path(path)
                for path in (*command.symbol_affected_file_paths, *command.changed_file_paths)
            }
            scoped = {
                node.id: node.path
                for node in command.graph_snapshot.graph.nodes
                if node.node_type in (GraphNodeType.FILE, GraphNodeType.SYMBOL)
                and node.path is not None
            }
            affected_ids = {
                node_id
                for node_id in affected_ids
                if node_id not in scoped or scoped[node_id] in keep
            }
        affected_nodes = [
            node
            for node in command.graph_snapshot.graph.nodes
            if node.id in affected_ids
        ]
        affected_file_paths = {
            node.path
            for node in affected_nodes
            if node.node_type == GraphNodeType.FILE and node.path is not None
        }
        return self.save_blast_radius(
            SaveBlastRadiusCommand(
                analysis_id=command.analysis_id,
                affected_files=sum(
                    node.node_type == GraphNodeType.FILE for node in affected_nodes
                ),
                affected_symbols=self._count_symbols_for_files(
                    command.graph_snapshot,
                    affected_file_paths,
                ),
                affected_modules=self._count_modules_for_files(
                    command.graph_snapshot,
                    affected_ids,
                ),
                affected_tests=len(set(command.affected_test_paths)),
                dependency_depth=dependency_depth,
            )
        )

    def _get_required(self, analysis_id: UUID) -> Analysis:
        analysis = self._store.get_by_id(analysis_id)
        if analysis is None:
            msg = f"Analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return analysis

    @staticmethod
    def _parse_status(status: str | None) -> AnalysisStatus | None:
        if status is None:
            return None
        try:
            return AnalysisStatus(status)
        except ValueError as exc:
            msg = f"Unsupported analysis status: {status}."
            raise ValidationError(msg) from exc

    @staticmethod
    def _parse_change_type(change_type: str) -> ChangedFileType:
        try:
            return ChangedFileType(change_type)
        except ValueError as exc:
            msg = f"Unsupported changed file type: {change_type}."
            raise ValidationError(msg) from exc

    @staticmethod
    def _traverse_reverse_dependencies(
        graph_snapshot: GraphSnapshot,
        start_ids: set[GraphNodeId],
    ) -> tuple[set[GraphNodeId], int]:
        existing_ids = graph_snapshot.graph.node_ids()
        affected = {node_id for node_id in start_ids if node_id in existing_ids}
        frontier = set(affected)
        max_depth = 0
        depth = 0
        while frontier:
            depth += 1
            next_frontier: set[GraphNodeId] = set()
            for edge in graph_snapshot.graph.edges:
                AnalysisApplicationService._collect_reverse_dependency(
                    edge,
                    frontier,
                    affected,
                    next_frontier,
                )
            if next_frontier:
                max_depth = depth
            frontier = next_frontier
        return affected, max_depth

    @staticmethod
    def _normalize_graph_path(path: str) -> str:
        return path.replace("\\", "/")

    @staticmethod
    def _count_symbols_for_files(
        graph_snapshot: GraphSnapshot,
        affected_file_paths: set[str],
    ) -> int:
        return sum(
            node.node_type == GraphNodeType.SYMBOL and node.path in affected_file_paths
            for node in graph_snapshot.graph.nodes
        )

    @staticmethod
    def _count_modules_for_files(
        graph_snapshot: GraphSnapshot,
        affected_file_ids: set[GraphNodeId],
    ) -> int:
        import_ids = {
            edge.target_id
            for edge in graph_snapshot.graph.edges
            if edge.source_id in affected_file_ids
            and edge.edge_type == GraphEdgeType.IMPORTS
        }
        module_ids = {
            edge.target_id
            for edge in graph_snapshot.graph.edges
            if edge.source_id in import_ids
            and edge.edge_type == GraphEdgeType.DEPENDS_ON
        }
        return sum(
            node.node_type == GraphNodeType.MODULE and node.id in module_ids
            for node in graph_snapshot.graph.nodes
        )

    @staticmethod
    def _collect_reverse_dependency(
        edge: GraphEdge,
        frontier: set[GraphNodeId],
        affected: set[GraphNodeId],
        next_frontier: set[GraphNodeId],
    ) -> None:
        if edge.target_id in frontier and edge.source_id not in affected:
            affected.add(edge.source_id)
            next_frontier.add(edge.source_id)
