"""Graph storage interfaces."""

from typing import Protocol
from uuid import UUID

from radius_graph.domain.entities import GraphSnapshot


class GraphStore(Protocol):
    """Persistence contract for graph snapshots."""

    def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        """Persist graph snapshot metadata/artifact."""

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return a graph snapshot for one analysis."""
