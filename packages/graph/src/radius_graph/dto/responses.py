"""Graph response DTOs."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_graph.domain.entities import GraphEdge, GraphNode, GraphSnapshot
from radius_graph.domain.slicing import (
    EDGES_PER_NODE,
    GraphSlice,
    slice_snapshot,
)

__all__ = [
    "EDGES_PER_NODE",
    "GraphEdgeResponse",
    "GraphNodeResponse",
    "GraphSnapshotResponse",
]


@dataclass(frozen=True, slots=True)
class GraphNodeResponse:
    """Graph node response DTO."""

    id: str
    node_type: str
    label: str
    path: str | None

    @classmethod
    def from_entity(cls, node: GraphNode) -> "GraphNodeResponse":
        """Create a response DTO from a graph node."""

        return cls(
            id=node.id.value,
            node_type=node.node_type.value,
            label=node.label,
            path=node.path,
        )


@dataclass(frozen=True, slots=True)
class GraphEdgeResponse:
    """Graph edge response DTO."""

    source_id: str
    target_id: str
    edge_type: str

    @classmethod
    def from_entity(cls, edge: GraphEdge) -> "GraphEdgeResponse":
        """Create a response DTO from a graph edge."""

        return cls(
            source_id=edge.source_id.value,
            target_id=edge.target_id.value,
            edge_type=edge.edge_type.value,
        )


@dataclass(frozen=True, slots=True)
class GraphSnapshotResponse:
    """Graph snapshot response DTO."""

    repository_id: UUID
    analysis_id: UUID
    node_count: int
    edge_count: int
    graph_version: str
    created_at: datetime
    nodes: tuple[GraphNodeResponse, ...]
    edges: tuple[GraphEdgeResponse, ...]
    # node_count / edge_count above always describe the whole stored graph;
    # the fields below describe the slice actually returned in nodes / edges.
    scope: str = "full"
    truncated: bool = False
    returned_node_count: int | None = None
    returned_edge_count: int | None = None

    @classmethod
    def from_entity(cls, snapshot: GraphSnapshot) -> "GraphSnapshotResponse":
        """Create a response DTO from a graph snapshot."""

        return cls(
            repository_id=snapshot.repository_id,
            analysis_id=snapshot.analysis_id,
            node_count=snapshot.node_count,
            edge_count=snapshot.edge_count,
            graph_version=snapshot.graph_version.value,
            created_at=snapshot.created_at,
            nodes=tuple(
                GraphNodeResponse.from_entity(node) for node in snapshot.graph.nodes
            ),
            edges=tuple(
                GraphEdgeResponse.from_entity(edge) for edge in snapshot.graph.edges
            ),
        )

    @classmethod
    def bounded(
        cls,
        snapshot: GraphSnapshot,
        *,
        limit: int,
        seed_paths: Iterable[str] | None = None,
        depth: int = 1,
    ) -> "GraphSnapshotResponse":
        """Bounded slice of an in-memory snapshot (see ``slice_snapshot``)."""

        return cls.from_slice(
            slice_snapshot(snapshot, limit=limit, seed_paths=seed_paths, depth=depth)
        )

    @classmethod
    def from_slice(cls, graph_slice: GraphSlice) -> "GraphSnapshotResponse":
        """Create a response DTO from a bounded graph slice."""

        return cls(
            repository_id=graph_slice.repository_id,
            analysis_id=graph_slice.analysis_id,
            node_count=graph_slice.node_count,
            edge_count=graph_slice.edge_count,
            graph_version=graph_slice.graph_version,
            created_at=graph_slice.created_at,
            nodes=tuple(GraphNodeResponse.from_entity(node) for node in graph_slice.nodes),
            edges=tuple(GraphEdgeResponse.from_entity(edge) for edge in graph_slice.edges),
            scope=graph_slice.scope,
            truncated=graph_slice.truncated,
            returned_node_count=len(graph_slice.nodes),
            returned_edge_count=len(graph_slice.edges),
        )
