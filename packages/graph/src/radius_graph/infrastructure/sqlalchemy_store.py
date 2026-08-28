"""SQLAlchemy graph store adapter."""

from uuid import UUID

from radius_shared.database import models as db_models
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion


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
        self._session.add_all(
            [
                db_models.GraphNode(
                    snapshot_id=row.id,
                    node_key=node.id.value,
                    node_type=node.node_type.value,
                    label=node.label,
                    path=node.path,
                )
                for node in snapshot.graph.nodes
            ]
        )
        self._session.add_all(
            [
                db_models.GraphEdge(
                    snapshot_id=row.id,
                    source_key=edge.source_id.value,
                    target_key=edge.target_id.value,
                    edge_type=edge.edge_type.value,
                )
                for edge in snapshot.graph.edges
            ]
        )
        self._session.flush()
        return snapshot

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return graph snapshot by analysis id."""

        row = self._session.scalar(
            select(db_models.GraphSnapshot)
            .where(db_models.GraphSnapshot.analysis_id == analysis_id)
            .options(
                selectinload(db_models.GraphSnapshot.nodes),
                selectinload(db_models.GraphSnapshot.edges),
            )
        )
        if row is None:
            return None
        return GraphSnapshot(
            repository_id=row.repository_id,
            analysis_id=row.analysis_id,
            graph=DependencyGraph(
                nodes=tuple(
                    GraphNode(
                        id=GraphNodeId(node.node_key),
                        node_type=GraphNodeType(node.node_type),
                        label=node.label,
                        path=node.path,
                    )
                    for node in sorted(row.nodes, key=lambda item: item.node_key)
                ),
                edges=tuple(
                    GraphEdge(
                        source_id=GraphNodeId(edge.source_key),
                        target_id=GraphNodeId(edge.target_key),
                        edge_type=GraphEdgeType(edge.edge_type),
                    )
                    for edge in sorted(
                        row.edges,
                        key=lambda item: (
                            item.source_key,
                            item.target_key,
                            item.edge_type,
                        ),
                    )
                ),
            ),
            graph_version=GraphVersion(row.graph_version),
            created_at=row.created_at,
        )
