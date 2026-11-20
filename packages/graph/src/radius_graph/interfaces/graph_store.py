"""Graph storage interfaces."""

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from radius_graph.domain.entities import GraphEdge, GraphNode, GraphSnapshot
from radius_graph.domain.slicing import GraphPage, GraphSlice


class GraphStore(Protocol):
    """Persistence contract for graph snapshots."""

    def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        """Persist graph snapshot metadata/artifact."""

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return a graph snapshot for one analysis."""

    def get_graph_slice(
        self,
        analysis_id: UUID,
        *,
        limit: int,
        seed_paths: Iterable[str] | None = None,
        depth: int = 1,
    ) -> GraphSlice | None:
        """Return the bounded slice ``slice_snapshot`` defines, or None."""

    def list_nodes(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphNode] | None:
        """Return one page of nodes in stored order, or None."""

    def list_edges(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphEdge] | None:
        """Return one page of edges in stored order, or None."""
