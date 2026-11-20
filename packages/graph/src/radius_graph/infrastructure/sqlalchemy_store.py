"""SQLAlchemy graph store adapter.

A snapshot of a real repository has tens of thousands of nodes and edges. Rows are written
with chunked bulk INSERTs and read back as plain column tuples, never as one ORM object per
row: ORM instances cost ~1 KB each and stayed in the session for the whole analysis, which
was a large part of the worker's peak memory (512 MB hosts ran out of memory).

The API reads bounded slices and pages with SQL (``get_graph_slice``, ``list_nodes``,
``list_edges``) and never materialises a whole snapshot: on a 0.1-CPU host that took
seconds of CPU and starved the health check. They use the order ``get_snapshot`` sorts
into (code point order of the keys), so a slice equals ``slice_snapshot`` applied to
``get_snapshot``.
"""

from collections.abc import Iterable, Iterator
from itertools import islice
from uuid import UUID, uuid4

from radius_shared.database import models as db_models
from sqlalchemy import ColumnElement, Table, delete, func, insert, or_, select
from sqlalchemy.orm import Session

from radius_graph.domain.entities import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
)
from radius_graph.domain.enums import GraphEdgeType, GraphNodeType
from radius_graph.domain.slicing import (
    EDGES_PER_NODE,
    GraphPage,
    GraphSlice,
    edge_sort_key,
    normalize_path,
)
from radius_graph.domain.value_objects import GraphNodeId, GraphVersion

#: Rows per INSERT statement (bounds the parameter list held in memory at once).
INSERT_CHUNK_ROWS = 2000

#: Keys per ``IN (...)`` list (below SQLite's historic 999-parameter limit).
IN_CHUNK_KEYS = 900

#: Every character ``str.strip()`` removes. A stored path that starts or ends with one,
#: contains a backslash or starts with ``./`` is not in normalised form, so it is
#: fetched as a candidate and normalised in Python, like ``normalize_path`` does.
STRIP_CHARACTERS = (
    "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0      "
    "          　"
)

_NODE_TABLE: Table = db_models.GraphNode.__table__
_EDGE_TABLE: Table = db_models.GraphEdge.__table__
_NODE_COLUMNS = (
    _NODE_TABLE.c.node_key,
    _NODE_TABLE.c.node_type,
    _NODE_TABLE.c.label,
    _NODE_TABLE.c.path,
)
_EDGE_COLUMNS = (
    _EDGE_TABLE.c.source_key,
    _EDGE_TABLE.c.target_key,
    _EDGE_TABLE.c.edge_type,
)


def _chunks[T](rows: Iterable[T], size: int = INSERT_CHUNK_ROWS) -> Iterator[list[T]]:
    iterator = iter(rows)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _node(node_key: str, node_type: str, label: str, path: str | None) -> GraphNode:
    return GraphNode(
        id=GraphNodeId(node_key),
        node_type=GraphNodeType(node_type),
        label=label,
        path=path,
    )


def _edge(source_key: str, target_key: str, edge_type: str) -> GraphEdge:
    return GraphEdge(
        source_id=GraphNodeId(source_key),
        target_id=GraphNodeId(target_key),
        edge_type=GraphEdgeType(edge_type),
    )


class SqlAlchemyGraphStore:
    """Persist graph snapshots, nodes, and edges in SQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_snapshot(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        """Persist graph snapshot metadata and artifact rows."""

        row = self._snapshot_row(snapshot.analysis_id)
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
            self._session.execute(insert(_NODE_TABLE), chunk)
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
            self._session.execute(insert(_EDGE_TABLE), chunk)
        return snapshot

    def get_snapshot(self, analysis_id: UUID) -> GraphSnapshot | None:
        """Return the whole graph snapshot by analysis id (the worker's read)."""

        row = self._snapshot_row(analysis_id)
        if row is None:
            return None
        # Sorted in Python, not ORDER BY: the order must not depend on the database collation.
        nodes = sorted(
            (
                _node(*values)
                for values in self._session.execute(
                    select(*_NODE_COLUMNS).where(_NODE_TABLE.c.snapshot_id == row.id)
                )
            ),
            key=lambda node: node.id.value,
        )
        edges = sorted(
            (
                _edge(*values)
                for values in self._session.execute(
                    select(*_EDGE_COLUMNS).where(_EDGE_TABLE.c.snapshot_id == row.id)
                )
            ),
            key=edge_sort_key,
        )
        return GraphSnapshot(
            repository_id=row.repository_id,
            analysis_id=row.analysis_id,
            graph=DependencyGraph(nodes=tuple(nodes), edges=tuple(edges)),
            graph_version=GraphVersion(row.graph_version),
            created_at=row.created_at,
        )

    def get_graph_slice(
        self,
        analysis_id: UUID,
        *,
        limit: int,
        seed_paths: Iterable[str] | None = None,
        depth: int = 1,
    ) -> GraphSlice | None:
        """Return ``slice_snapshot(get_snapshot(analysis_id), ...)``, computed in SQL.

        Reads only the returned nodes, the keys met within ``depth`` hops (``impact``,
        stopping after the hop that passes ``limit``) and the edges leaving returned
        nodes; the totals come from ``COUNT``.
        """

        row = self._snapshot_row(analysis_id)
        if row is None:
            return None
        node_count = self._count(_NODE_TABLE, row.id)
        if seed_paths is None:
            scope = "full"
            kept = self._node_page(row.id, limit=limit, offset=0)
            nodes_cut = node_count > limit
        else:
            scope = "impact"
            ranked = self._impact_ranking(row.id, seed_paths, depth, limit)
            nodes_cut = len(ranked) > limit
            kept = self._nodes_by_key(row.id, ranked[:limit])
        edges = self._edges_among(row.id, {node.id.value for node in kept})
        max_edges = limit * EDGES_PER_NODE
        return GraphSlice(
            repository_id=row.repository_id,
            analysis_id=row.analysis_id,
            graph_version=row.graph_version,
            created_at=row.created_at,
            node_count=node_count,
            edge_count=self._count(_EDGE_TABLE, row.id),
            nodes=tuple(kept),
            edges=tuple(edges[:max_edges]),
            scope=scope,
            truncated=nodes_cut or len(edges) > max_edges,
        )

    def list_nodes(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphNode] | None:
        """Return one page of nodes in ``get_snapshot`` order, plus the total."""

        row = self._snapshot_row(analysis_id)
        if row is None:
            return None
        return GraphPage(
            items=tuple(self._node_page(row.id, limit=limit, offset=offset)),
            total=self._count(_NODE_TABLE, row.id),
        )

    def list_edges(
        self, analysis_id: UUID, *, limit: int, offset: int = 0
    ) -> GraphPage[GraphEdge] | None:
        """Return one page of edges in ``get_snapshot`` order, plus the total."""

        row = self._snapshot_row(analysis_id)
        if row is None:
            return None
        statement = (
            select(*_EDGE_COLUMNS)
            .where(_EDGE_TABLE.c.snapshot_id == row.id)
            .order_by(*(self._code_point(column) for column in _EDGE_COLUMNS))
            .limit(limit)
            .offset(offset)
        )
        return GraphPage(
            items=tuple(_edge(*values) for values in self._session.execute(statement)),
            total=self._count(_EDGE_TABLE, row.id),
        )

    def _snapshot_row(self, analysis_id: UUID) -> db_models.GraphSnapshot | None:
        return self._session.scalar(
            select(db_models.GraphSnapshot).where(
                db_models.GraphSnapshot.analysis_id == analysis_id
            )
        )

    def _count(self, table: Table, snapshot_id: UUID) -> int:
        return self._session.scalar(
            select(func.count()).select_from(table).where(table.c.snapshot_id == snapshot_id)
        )

    def _code_point(self, column: ColumnElement[str]) -> ColumnElement[str]:
        """Order by code point, as Python sorts (PostgreSQL ``C``; SQLite ``BINARY``)."""

        if self._session.get_bind().dialect.name == "postgresql":
            return column.collate("C")
        return column

    def _node_page(self, snapshot_id: UUID, *, limit: int, offset: int) -> list[GraphNode]:
        statement = (
            select(*_NODE_COLUMNS)
            .where(_NODE_TABLE.c.snapshot_id == snapshot_id)
            .order_by(self._code_point(_NODE_TABLE.c.node_key))
            .limit(limit)
            .offset(offset)
        )
        return [_node(*values) for values in self._session.execute(statement)]

    def _nodes_by_key(self, snapshot_id: UUID, keys: list[str]) -> list[GraphNode]:
        """Nodes for ``keys`` (all stored), in the order of ``keys``."""

        by_key: dict[str, GraphNode] = {}
        for chunk in _chunks(keys, IN_CHUNK_KEYS):
            for values in self._session.execute(
                select(*_NODE_COLUMNS).where(
                    _NODE_TABLE.c.snapshot_id == snapshot_id,
                    _NODE_TABLE.c.node_key.in_(chunk),
                )
            ):
                by_key[values[0]] = _node(*values)
        return [by_key[key] for key in keys]

    def _impact_ranking(
        self,
        snapshot_id: UUID,
        seed_paths: Iterable[str],
        depth: int,
        limit: int,
    ) -> list[str]:
        """Keys of stored nodes on ``seed_paths`` or within ``depth`` hops, nearest first.

        Breadth-first, one round of edge queries per hop, also through edge endpoints
        that are not stored nodes (as ``slice_snapshot`` does). Once more than ``limit``
        stored nodes are known it stops: nodes of later hops rank after them, so the
        first ``limit`` keys and "more than ``limit``" are already decided.
        """

        wanted = {normalize_path(path) for path in seed_paths if path.strip()}
        if not wanted:
            return []
        distance = dict.fromkeys(self._keys_on_paths(snapshot_id, wanted), 0)
        stored = set(distance)
        frontier = set(distance)
        hops = 0
        while frontier and hops < depth and len(stored) <= limit:
            hops += 1
            frontier = self._neighbour_keys(snapshot_id, frontier) - distance.keys()
            distance.update(dict.fromkeys(frontier, hops))
            stored |= self._stored_keys(snapshot_id, frontier)
        return sorted(stored, key=lambda key: (distance[key], key))

    def _keys_on_paths(self, snapshot_id: UUID, wanted: set[str]) -> set[str]:
        """Keys of nodes whose normalised path is in ``wanted``."""

        path = _NODE_TABLE.c.path
        base = select(_NODE_TABLE.c.node_key, path).where(
            _NODE_TABLE.c.snapshot_id == snapshot_id, path.is_not(None)
        )
        strip = tuple(STRIP_CHARACTERS)
        not_normalised = or_(
            path.contains("\\", autoescape=True),
            path.startswith("./", autoescape=True),
            func.substr(path, 1, 1).in_(strip),
            func.substr(path, func.length(path), 1).in_(strip),
        )
        candidates = list(self._session.execute(base.where(not_normalised)))
        for chunk in _chunks(sorted(wanted), IN_CHUNK_KEYS):
            candidates.extend(self._session.execute(base.where(path.in_(chunk))))
        return {key for key, value in candidates if normalize_path(value) in wanted}

    def _neighbour_keys(self, snapshot_id: UUID, keys: set[str]) -> set[str]:
        """Other endpoints of the edges touching ``keys``, in either direction."""

        found: set[str] = set()
        source, target = _EDGE_TABLE.c.source_key, _EDGE_TABLE.c.target_key
        for chunk in _chunks(sorted(keys), IN_CHUNK_KEYS):
            for other_end, known_end in ((target, source), (source, target)):
                found.update(
                    self._session.scalars(
                        select(other_end).where(
                            _EDGE_TABLE.c.snapshot_id == snapshot_id,
                            known_end.in_(chunk),
                        )
                    )
                )
        return found

    def _stored_keys(self, snapshot_id: UUID, keys: set[str]) -> set[str]:
        """The subset of ``keys`` that are stored nodes."""

        found: set[str] = set()
        for chunk in _chunks(sorted(keys), IN_CHUNK_KEYS):
            found.update(
                self._session.scalars(
                    select(_NODE_TABLE.c.node_key).where(
                        _NODE_TABLE.c.snapshot_id == snapshot_id,
                        _NODE_TABLE.c.node_key.in_(chunk),
                    )
                )
            )
        return found

    def _edges_among(self, snapshot_id: UUID, keys: set[str]) -> list[GraphEdge]:
        """Edges whose both ends are in ``keys``, in ``get_snapshot`` order."""

        edges: list[GraphEdge] = []
        for chunk in _chunks(sorted(keys), IN_CHUNK_KEYS):
            edges.extend(
                _edge(source_key, target_key, edge_type)
                for source_key, target_key, edge_type in self._session.execute(
                    select(*_EDGE_COLUMNS).where(
                        _EDGE_TABLE.c.snapshot_id == snapshot_id,
                        _EDGE_TABLE.c.source_key.in_(chunk),
                    )
                )
                if target_key in keys
            )
        edges.sort(key=edge_sort_key)
        return edges
