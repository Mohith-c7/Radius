"""SQLAlchemy graph store adapter.

A snapshot of a real repository has tens of thousands of nodes and edges. Rows are written
with chunked bulk INSERTs and read back as plain column tuples, never as one ORM object per
row: ORM instances cost ~1 KB each and stayed in the session for the whole analysis, which
was a large part of the worker's peak memory (512 MB hosts ran out of memory).
"""

from collections.abc import Iterable, Iterator
from itertools import islice
from uuid import UUID, uuid4

from radius_shared.database import models as db_models
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion

#: Rows per INSERT statement (bounds the parameter list held in memory at once).
INSERT_CHUNK_ROWS = 2000


def _chunks(rows: Iterable[dict], size: int = INSERT_CHUNK_ROWS) -> Iterator[list[dict]]:
    iterator = iter(rows)
    while chunk := list(islice(iterator, size)):
        yield chunk


class SqlAlchemyGraphStore:
    """Persist graph snapshots, nodes, and edges in SQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        """Persist graph snapshot metadata and artifact rows."""

        row = self._session.scalar(
            select(db_models.GraphSnapshot).where(
                db_models.GraphSnapshot.analysis_id == snapshot.analysis_id
            )
        )
        if row is None:
            row = db_models.GraphSnapshot(
                analysis_id=snapshot.analysis_id,
                repository_id=snapshot.repository_id,
                node_count=snapshot.node_count,
                edge_count=snapshot.edge_count,
                graph_version=snapshot.graph_version.value,
                created_at=snapshot.created_at,
            )
            self._session.add(row)
        else:
            self._session.execute(
                delete(db_models.GraphNode).where(
                    db_models.GraphNode.snapshot_id == row.id
                )
            )
            self._session.execute(
                delete(db_models.GraphEdge).where(
                    db_models.GraphEdge.snapshot_id == row.id
                )
            )

        row.repository_id = snapshot.repository_id
        row.node_count = snapshot.node_count
        row.edge_count = snapshot.edge_count
        row.graph_version = snapshot.graph_version.value
        row.created_at = snapshot.created_at
        self._session.flush()
        snapshot_id = row.id
        node_rows = (
            {
                "id": uuid4(),
                "snapshot_id": snapshot_id,
                "node_key": node.id.value,
                "node_type": node.node_type.value,
                "label": node.label,
                "path": node.path,
            }
            for node in snapshot.graph.nodes
        )
        for chunk in _chunks(node_rows):
            self._session.execute(insert(db_models.GraphNode.__table__), chunk)
        edge_rows = (
            {
                "id": uuid4(),
                "snapshot_id": snapshot_id,
                "source_key": edge.source_id.value,
                "target_key": edge.target_id.value,
                "edge_type": edge.edge_type.value,
            }
            for edge in snapshot.graph.edges
        )
        for chunk in _chunks(edge_rows):
            self._session.execute(insert(db_models.GraphEdge.__table__), chunk)
        return snapshot

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return graph snapshot by analysis id."""

        row = self._session.scalar(
            select(db_models.GraphSnapshot).where(
                db_models.GraphSnapshot.analysis_id == analysis_id
            )
        )
        if row is None:
            return None
        node_table, edge_table = db_models.GraphNode.__table__, db_models.GraphEdge.__table__
        # Sorted in Python, not ORDER BY: the order must not depend on the database collation.
        nodes = sorted(
            (
                GraphNode(
                    id=GraphNodeId(node_key),
                    node_type=GraphNodeType(node_type),
                    label=label,
                    path=path,
                )
                for node_key, node_type, label, path in self._session.execute(
                    select(
                        node_table.c.node_key,
                        node_table.c.node_type,
                        node_table.c.label,
                        node_table.c.path,
                    ).where(node_table.c.snapshot_id == row.id)
                )
            ),
            key=lambda node: node.id.value,
        )
        edges = sorted(
            (
                GraphEdge(
                    source_id=GraphNodeId(source_key),
                    target_id=GraphNodeId(target_key),
                    edge_type=GraphEdgeType(edge_type),
                )
                for source_key, target_key, edge_type in self._session.execute(
                    select(
                        edge_table.c.source_key,
                        edge_table.c.target_key,
                        edge_table.c.edge_type,
                    ).where(edge_table.c.snapshot_id == row.id)
                )
            ),
            key=lambda edge: (edge.source_id.value, edge.target_id.value, edge.edge_type.value),
        )
        return GraphSnapshot(
            repository_id=row.repository_id,
            analysis_id=row.analysis_id,
            graph=DependencyGraph(nodes=tuple(nodes), edges=tuple(edges)),
            graph_version=GraphVersion(row.graph_version),
            created_at=row.created_at,
        )
