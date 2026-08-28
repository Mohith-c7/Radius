"""In-memory graph infrastructure adapters."""

from uuid import UUID

from radius_graph.domain.entities import DependencyGraph, GraphSnapshot
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
