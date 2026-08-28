"""Graph infrastructure tests."""

from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNodeId,
)
from radius_graph.infrastructure import InMemoryGraphTraversal


def test_in_memory_graph_traversal_finds_transitive_reverse_dependencies() -> None:
    changed = GraphNodeId("file:src/core.py")
    direct = GraphNodeId("file:src/service.py")
    indirect = GraphNodeId("file:src/api.py")
    graph = DependencyGraph(
        edges=(
            GraphEdge(
                source_id=direct,
                target_id=changed,
                edge_type=GraphEdgeType.IMPORTS,
            ),
            GraphEdge(
                source_id=indirect,
                target_id=direct,
                edge_type=GraphEdgeType.IMPORTS,
            ),
        )
    )

    result = InMemoryGraphTraversal(graph).reverse_dependencies({changed})

    assert result == {direct, indirect}


def test_in_memory_graph_traversal_honors_max_depth() -> None:
    changed = GraphNodeId("file:src/core.py")
    direct = GraphNodeId("file:src/service.py")
    indirect = GraphNodeId("file:src/api.py")
    graph = DependencyGraph(
        edges=(
            GraphEdge(
                source_id=direct,
                target_id=changed,
                edge_type=GraphEdgeType.IMPORTS,
            ),
            GraphEdge(
                source_id=indirect,
                target_id=direct,
                edge_type=GraphEdgeType.IMPORTS,
            ),
        )
    )

    result = InMemoryGraphTraversal(graph).reverse_dependencies(
        {changed},
        max_depth=1,
    )

    assert result == {direct}
