"""Bounded slices of a graph snapshot (what the graph API returns).

``slice_snapshot`` is the reference algorithm over an in-memory snapshot. The SQL
store computes the same slice with queries, without loading the whole snapshot
(a real repository has tens of thousands of nodes and edges).
"""

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

# A bounded slice returns at most this many edges per returned node, so a dense
# slice cannot blow the response size up through its edges alone.
EDGES_PER_NODE = 4


@dataclass(frozen=True, slots=True)
class GraphSlice:
    """Bounded part of a snapshot; ``node_count`` / ``edge_count`` are the totals."""

    repository_id: UUID
    analysis_id: UUID
    graph_version: str
    created_at: datetime
    node_count: int
    edge_count: int
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    scope: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class GraphPage[T]:
    """One ``limit``/``offset`` page of nodes or edges and the stored total."""

    items: tuple[T, ...]
    total: int


def normalize_path(path: str) -> str:
    """Repository-relative POSIX form used to match changed files to nodes."""

    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def edge_sort_key(edge: GraphEdge) -> tuple[str, str, str]:
    """Stored edge order: source, target, type."""

    return (edge.source_id.value, edge.target_id.value, edge.edge_type.value)


def slice_snapshot(
    snapshot: GraphSnapshot,
    *,
    limit: int,
    seed_paths: Iterable[str] | None = None,
    depth: int = 1,
) -> GraphSlice:
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
    return GraphSlice(
        repository_id=snapshot.repository_id,
        analysis_id=snapshot.analysis_id,
        graph_version=snapshot.graph_version.value,
        created_at=snapshot.created_at,
        node_count=snapshot.node_count,
        edge_count=snapshot.edge_count,
        nodes=tuple(kept),
        edges=tuple(edges[:max_edges]),
        scope=scope,
        truncated=truncated,
    )


def _impact_nodes(
    graph: DependencyGraph,
    seed_paths: Iterable[str],
    depth: int,
) -> list[GraphNode]:
    """Nodes on the seed paths plus their ``depth``-hop neighbourhood, nearest first."""

    wanted = {normalize_path(path) for path in seed_paths if path.strip()}
    distance: dict[GraphNodeId, int] = {
        node.id: 0
        for node in graph.nodes
        if node.path is not None and normalize_path(node.path) in wanted
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
