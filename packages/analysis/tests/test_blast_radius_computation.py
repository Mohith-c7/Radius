"""Blast-radius computation tests."""

from __future__ import annotations

from uuid import UUID, uuid4

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, BlastRadius, ChangedFile
from radius_analysis.dto import ComputeBlastRadiusCommand, StartAnalysisCommand
from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphSnapshot,
)


class InMemoryAnalysisStore:
    """Small fake used to exercise blast-radius service behavior."""

    def __init__(self) -> None:
        self.analyses: dict[UUID, Analysis] = {}

    def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        return self.analyses.get(analysis_id)

    def list(
        self,
        repository_id: UUID | None = None,
        pull_request_id: UUID | None = None,
        status: AnalysisStatus | None = None,
    ) -> list[Analysis]:
        return list(self.analyses.values())

    def save(self, analysis: Analysis) -> Analysis:
        analysis.id = analysis.id or uuid4()
        self.analyses[analysis.id] = analysis
        return analysis

    def update_status(
        self,
        analysis_id: UUID,
        status: AnalysisStatus,
    ) -> Analysis:
        analysis = self.analyses[analysis_id]
        analysis.status = status
        return analysis

    def replace_changed_files(
        self,
        analysis_id: UUID,
        changed_files: list[ChangedFile],
    ) -> list[ChangedFile]:
        self.analyses[analysis_id].changed_files = changed_files
        return changed_files

    def save_blast_radius(self, blast_radius: BlastRadius) -> BlastRadius:
        saved = BlastRadius(
            id=blast_radius.id or uuid4(),
            analysis_id=blast_radius.analysis_id,
            affected_files=blast_radius.affected_files,
            affected_symbols=blast_radius.affected_symbols,
            affected_modules=blast_radius.affected_modules,
            affected_tests=blast_radius.affected_tests,
            dependency_depth=blast_radius.dependency_depth,
        )
        self.analyses[blast_radius.analysis_id].blast_radius = saved
        return saved

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        return self.analyses[analysis_id].blast_radius


def test_compute_blast_radius_counts_changed_and_reverse_dependent_nodes() -> None:
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(store)
    analysis = service.start_analysis(
        StartAnalysisCommand(
            repository_id=uuid4(),
            pull_request_id=uuid4(),
            commit_sha="a" * 40,
        )
    )
    snapshot = _graph_snapshot(analysis.id)

    response = service.compute_blast_radius(
        ComputeBlastRadiusCommand(
            analysis_id=analysis.id,
            graph_snapshot=snapshot,
            changed_file_paths=("src/core.py",),
        )
    )

    assert response.affected_files == 3
    assert response.affected_symbols == 1
    # Modules are the directories holding affected files: all three are in src/.
    assert response.affected_modules == 1
    assert response.affected_tests == 0
    assert response.dependency_depth == 2


def _graph_snapshot(analysis_id: UUID) -> GraphSnapshot:
    core = GraphNodeId("file:src/core.py")
    service = GraphNodeId("file:src/service.py")
    api = GraphNodeId("file:src/api.py")
    symbol = GraphNodeId("symbol:src/service.py:handle")
    return GraphSnapshot(
        repository_id=uuid4(),
        analysis_id=analysis_id,
        graph=DependencyGraph(
            nodes=(
                GraphNode(core, GraphNodeType.FILE, "src/core.py", "src/core.py"),
                GraphNode(
                    service,
                    GraphNodeType.FILE,
                    "src/service.py",
                    "src/service.py",
                ),
                GraphNode(api, GraphNodeType.FILE, "src/api.py", "src/api.py"),
                GraphNode(symbol, GraphNodeType.SYMBOL, "handle", "src/service.py"),
            ),
            edges=(
                GraphEdge(service, core, GraphEdgeType.DEPENDS_ON),
                GraphEdge(api, service, GraphEdgeType.DEPENDS_ON),
                GraphEdge(symbol, service, GraphEdgeType.CONTAINS),
            ),
        ),
    )


def test_symbol_scope_limits_affected_files_and_symbols() -> None:
    service = AnalysisApplicationService(InMemoryAnalysisStore())
    analysis = service.start_analysis(
        StartAnalysisCommand(uuid4(), uuid4(), "a" * 40)
    )
    response = service.compute_blast_radius(
        ComputeBlastRadiusCommand(
            analysis_id=analysis.id,
            graph_snapshot=_graph_snapshot(analysis.id),
            changed_file_paths=("src/core.py",),
            symbol_affected_file_paths=("src/core.py",),
        )
    )

    assert response.affected_files == 1
    assert response.affected_symbols == 0


def test_affected_modules_count_directories_not_imported_packages() -> None:
    """Production showed 297 "modules" for 152 affected files: every import specifier
    of every affected file (react, next/link, pydantic, ...) was counted."""

    service = AnalysisApplicationService(InMemoryAnalysisStore())
    analysis = service.start_analysis(StartAnalysisCommand(uuid4(), uuid4(), "a" * 40))
    api = GraphNodeId("file:apps/dashboard/lib/api.ts")
    page = GraphNodeId("file:apps/dashboard/app/profile/page.tsx")
    test = GraphNodeId("file:apps/dashboard/tests/api.test.mjs")
    unrelated = GraphNodeId("file:apps/api/src/radius_api/main.py")
    nodes = [
        GraphNode(api, GraphNodeType.FILE, "api.ts", "apps/dashboard/lib/api.ts"),
        GraphNode(page, GraphNodeType.FILE, "page.tsx", "apps/dashboard/app/profile/page.tsx"),
        GraphNode(test, GraphNodeType.FILE, "api.test.mjs", "apps/dashboard/tests/api.test.mjs"),
        GraphNode(unrelated, GraphNodeType.FILE, "main.py", "apps/api/src/radius_api/main.py"),
    ]
    edges = [
        GraphEdge(page, api, GraphEdgeType.DEPENDS_ON),
        GraphEdge(test, api, GraphEdgeType.DEPENDS_ON),
    ]
    for owner in (api, page, test):
        for package in ("react", "next/link", "node:test", "zod", "clsx", "lucide-react"):
            import_id = GraphNodeId(f"import:{owner.value}:{package}")
            module_id = GraphNodeId(f"module:{package}")
            nodes.append(GraphNode(import_id, GraphNodeType.IMPORT, package, owner.value))
            if all(node.id != module_id for node in nodes):
                nodes.append(GraphNode(module_id, GraphNodeType.MODULE, package))
            edges.append(GraphEdge(owner, import_id, GraphEdgeType.IMPORTS))
            edges.append(GraphEdge(import_id, module_id, GraphEdgeType.DEPENDS_ON))
    snapshot = GraphSnapshot(
        repository_id=uuid4(),
        analysis_id=analysis.id,
        graph=DependencyGraph(nodes=tuple(nodes), edges=tuple(edges)),
    )

    response = service.compute_blast_radius(
        ComputeBlastRadiusCommand(
            analysis_id=analysis.id,
            graph_snapshot=snapshot,
            changed_file_paths=("apps/dashboard/lib/api.ts",),
        )
    )

    assert response.affected_files == 3
    assert response.affected_modules == 3  # lib/, app/profile/, tests/
