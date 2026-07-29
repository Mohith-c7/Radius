"""Graph traversal interfaces."""

from typing import Protocol

from radius_graph.domain.value_objects import GraphNodeId


class GraphTraversal(Protocol):
    """Traversal contract for dependency graphs."""

    def reverse_dependencies(
        self,
        start_ids: set[GraphNodeId],
        max_depth: int | None = None,
    ) -> set[GraphNodeId]:
        """Return reverse dependencies for the starting node ids."""
