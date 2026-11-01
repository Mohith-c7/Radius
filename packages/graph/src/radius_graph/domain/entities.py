"""Graph domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One node in a repository relationship graph."""

    id: GraphNodeId
    node_type: GraphNodeType
    label: str
    path: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            msg = "Graph node label cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """Directed relationship between two graph nodes."""

    source_id: GraphNodeId
    target_id: GraphNodeId
    edge_type: GraphEdgeType

    def __post_init__(self) -> None:
        if self.source_id == self.target_id:
            msg = "Graph edge cannot point to itself."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Repository dependency graph."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    def node_ids(self) -> set[GraphNodeId]:
        """Return the ids contained in this graph."""

        return {node.id for node in self.nodes}

    def reverse_dependencies(self, node_id: GraphNodeId) -> set[GraphNodeId]:
        """Return nodes with direct edges into the requested node."""

        return {edge.source_id for edge in self.edges if edge.target_id == node_id}


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Graph metadata generated for an analysis."""

    repository_id: UUID
    analysis_id: UUID
    graph: DependencyGraph
    graph_version: GraphVersion = field(default_factory=lambda: GraphVersion("v1"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def node_count(self) -> int:
        """Return graph node count."""

        return len(self.graph.nodes)

    @property
    def edge_count(self) -> int:
        """Return graph edge count."""

        return len(self.graph.edges)
