"""External interfaces for the graph domain."""

from radius_graph.interfaces.graph_store import GraphStore
from radius_graph.interfaces.traversal import GraphTraversal

__all__ = ["GraphStore", "GraphTraversal"]
