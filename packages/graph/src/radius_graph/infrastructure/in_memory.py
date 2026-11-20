"""In-memory graph infrastructure adapters."""

from collections.abc import Iterable
from uuid import UUID

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.slicing import GraphPage, GraphSlice, slice_snapshot
from radius_graph.domain.value_objects import GraphNodeId


class InMemoryGraphStore:
    """Stores graph snapshots in memory for tests/local orchestration."""

    def __init__(self) -> None:
        self._snapshots: dict[UUID, GraphSnapshot] = {}

    def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        """Persist graph snapshot metadata/artifact."""

        self._snapshots[snapshot.analysis_id] = snapshot
        return snapshot

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return a graph snapshot for one analysis."""

        return self._snapshots.get(analysis_id)

    def get_graph_slice(
        self,
        analysis_id: UUID,
        *,
        limit: int,
        seed_paths: Iterable[str] | None = None,
        depth: int = 1,
    ) -> GraphSlice | None:
        """Return a bounded slice of one snapshot (see ``slice_snapshot``)."""

        snapshot = self._snapshots.get(analysis_id)
        if snapshot is None:
            return None
        return slice_snapshot(snapshot, limit=limit, seed_paths=seed_paths, depth=depth)

    def list_nodes(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphNode] | None:
        """Return one page of nodes in stored order."""

        snapshot = self._snapshots.get(analysis_id)
        if snapshot is None:
            return None
        nodes = snapshot.graph.nodes
        return GraphPage(items=nodes[offset : offset + limit], total=len(nodes))

    def list_edges(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphEdge] | None:
        """Return one page of edges in stored order."""

        snapshot = self._snapshots.get(analysis_id)
        if snapshot is None:
            return None
        edges = snapshot.graph.edges
        return GraphPage(items=edges[offset : offset + limit], total=len(edges))


class InMemoryGraphTraversal:
    """Traverse an in-memory dependency graph."""

    def __init__(self, graph: DependencyGraph) -> None:
        self._graph = graph

    def reverse_dependencies(
        self,
        start_ids: set[GraphNodeId],
        max_depth: int | None = None,
    ) -> set[GraphNodeId]:
        """Return transitive reverse dependencies for the starting node ids."""

        visited: set[GraphNodeId] = set()
        frontier = set(start_ids)
        depth = 0
        while frontier and (max_depth is None or depth < max_depth):
            next_frontier: set[GraphNodeId] = set()
            for node_id in frontier:
                for dependent in self._graph.reverse_dependencies(node_id):
                    if dependent not in visited and dependent not in start_ids:
                        visited.add(dependent)
                        next_frontier.add(dependent)
            frontier = next_frontier
            depth += 1
        return visited
