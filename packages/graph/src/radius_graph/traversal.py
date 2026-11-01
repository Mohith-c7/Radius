"""Deterministic reverse-dependency traversal over file nodes."""

from __future__ import annotations

from collections import deque

from radius_graph.domain.entities import DependencyGraph
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType


def file_dependents(
    graph: DependencyGraph,
    file_paths: tuple[str, ...] | list[str] | set[str],
) -> dict[str, frozenset[str]]:
    """Return, per file, every repository file that transitively depends on it.

    Only resolved file-to-file ``DEPENDS_ON`` edges are followed, so the result
    contains *direct and transitive* static import dependents. Each entry
    includes the file itself when it is present in the graph. Files missing
    from the graph map to an empty set, which callers must treat as
    "unknown impact", not "no impact".
    """

    file_ids = {
        node.id: node.path
        for node in graph.nodes
        if node.node_type == GraphNodeType.FILE and node.path is not None
    }
    reverse: dict[object, list[object]] = {}
    for edge in graph.edges:
        if (
            edge.edge_type == GraphEdgeType.DEPENDS_ON
            and edge.source_id in file_ids
            and edge.target_id in file_ids
        ):
            reverse.setdefault(edge.target_id, []).append(edge.source_id)

    id_by_path = {path: node_id for node_id, path in file_ids.items()}
    result: dict[str, frozenset[str]] = {}
    for path in file_paths:
        normalized = path.replace("\\", "/")
        start = id_by_path.get(normalized)
        if start is None:
            result[path] = frozenset()
            continue
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for dependent in reverse.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    queue.append(dependent)
        result[path] = frozenset(file_ids[node_id] for node_id in seen)
    return result
