"""Graph response DTOs."""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.value_objects import GraphNodeId

# A bounded payload returns at most this many edges per returned node, so a
# dense slice cannot blow the response size up through its edges alone.
EDGES_PER_NODE = 4


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
        """Return at most ``limit`` nodes (and ``EDGES_PER_NODE * limit`` edges).

        Without ``seed_paths`` the slice is the stored graph in stored order
        (``scope="full"``). With ``seed_paths`` it is the nodes whose path is one
        of them plus every node within ``depth`` hops in either edge direction,
        nearest first (``scope="impact"``). Only edges between returned nodes
        are included. ``truncated`` says whether anything was cut by the limit.
        """

        graph = snapshot.graph
        if seed_paths is None:
            scope, ordered = "full", list(graph.nodes)
        else:
            scope, ordered = "impact", _impact_nodes(graph, seed_paths, depth)
        kept = ordered[:limit]
        kept_ids = {node.id for node in kept}
        edges = [
            edge
            for edge in graph.edges
            if edge.source_id in kept_ids and edge.target_id in kept_ids
        ]
        max_edges = limit * EDGES_PER_NODE
        truncated = len(ordered) > limit or len(edges) > max_edges
        edges = edges[:max_edges]
        return cls(
            repository_id=snapshot.repository_id,
            analysis_id=snapshot.analysis_id,
            node_count=snapshot.node_count,
            edge_count=snapshot.edge_count,
            graph_version=snapshot.graph_version.value,
            created_at=snapshot.created_at,
            nodes=tuple(GraphNodeResponse.from_entity(node) for node in kept),
            edges=tuple(GraphEdgeResponse.from_entity(edge) for edge in edges),
            scope=scope,
            truncated=truncated,
            returned_node_count=len(kept),
            returned_edge_count=len(edges),
        )


def _normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _impact_nodes(
    graph: DependencyGraph,
    seed_paths: Iterable[str],
    depth: int,
) -> list[GraphNode]:
    """Nodes on the seed paths plus their ``depth``-hop neighbourhood, nearest first."""

    wanted = {_normalize_path(path) for path in seed_paths if path.strip()}
    distance: dict[GraphNodeId, int] = {
        node.id: 0
        for node in graph.nodes
        if node.path is not None and _normalize_path(node.path) in wanted
    }
    if depth > 0 and distance:
        neighbours: dict[GraphNodeId, list[GraphNodeId]] = {}
        for edge in graph.edges:
            neighbours.setdefault(edge.source_id, []).append(edge.target_id)
            neighbours.setdefault(edge.target_id, []).append(edge.source_id)
        queue = deque(distance)
        while queue:
            current = queue.popleft()
            hops = distance[current] + 1
            if hops > depth:
                continue
            for neighbour in neighbours.get(current, ()):
                if neighbour not in distance:
                    distance[neighbour] = hops
                    queue.append(neighbour)
    selected = [node for node in graph.nodes if node.id in distance]
    selected.sort(key=lambda node: distance[node.id])  # stable: keeps stored order
    return selected
