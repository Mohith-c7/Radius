"""Graph domain tests."""

import pytest
from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphVersion,
)


def test_graph_value_objects_reject_empty_values() -> None:
    with pytest.raises(ValueError, match="Graph node id cannot be empty"):
        GraphNodeId("")

    with pytest.raises(ValueError, match="Graph version cannot be empty"):
        GraphVersion(" ")


def test_graph_node_requires_label() -> None:
    with pytest.raises(ValueError, match="Graph node label cannot be empty"):
        GraphNode(
            id=GraphNodeId("file:src/app.py"),
            node_type=GraphNodeType.FILE,
            label="",
        )


def test_graph_edge_rejects_self_reference() -> None:
    node_id = GraphNodeId("file:src/app.py")

    with pytest.raises(ValueError, match="cannot point to itself"):
        GraphEdge(
            source_id=node_id,
            target_id=node_id,
            edge_type=GraphEdgeType.DEPENDS_ON,
        )


def test_dependency_graph_reverse_dependencies() -> None:
    source = GraphNodeId("file:src/app.py")
    target = GraphNodeId("module:os")
    graph = DependencyGraph(
        edges=(
            GraphEdge(
                source_id=source,
                target_id=target,
                edge_type=GraphEdgeType.IMPORTS,
            ),
        )
    )

    assert graph.reverse_dependencies(target) == {source}
