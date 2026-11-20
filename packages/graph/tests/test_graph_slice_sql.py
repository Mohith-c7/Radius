"""The SQL graph slice and pages equal the in-Python reference on the same snapshot."""

import random
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphSnapshot,
    slice_snapshot,
)
from radius_graph.infrastructure import SqlAlchemyGraphStore
from radius_shared.database.base import Base
from radius_shared.database.enums import AnalysisStatus, RepositoryVisibility
from radius_shared.database.models import Analysis, Organization, Repository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Paths in normalised and non-normalised forms; keys whose code point order differs
# from a case-insensitive or locale order ("B" < "a" < "e" < "é").
_PATHS = (
    "src/a.py",
    "./src/b.py",
    "src\\c.py",
    " src/d.py\t",
    "src/é.py",
    "src/B.py",
    "lib/x.py",
    None,
)
_SEEDS = (
    (),
    ("src/a.py",),
    ("./src/a.py", "src\\c.py"),
    ("src/b.py", " src/d.py ", "src/é.py"),
    ("src/B.py", "lib/x.py", "", "   ", "missing.py"),
)


def _random_graph(seed: int) -> DependencyGraph:
    rng = random.Random(seed)
    nodes = []
    for index in range(rng.randrange(8, 40)):
        path = rng.choice(_PATHS)
        key = f"{rng.choice('aBeé')}{index}:{path or 'none'}"
        nodes.append(
            GraphNode(GraphNodeId(key), rng.choice(list(GraphNodeType)), key, path)
        )
    keys = [node.id.value for node in nodes] + ["ghost:1", "ghost:2"]  # dangling ends
    edges = {
        (source, target, rng.choice(list(GraphEdgeType)))
        for source, target in (
            rng.sample(keys, 2) for _ in range(rng.randrange(0, 120))
        )
    }
    return DependencyGraph(
        nodes=tuple(rng.sample(nodes, len(nodes))),
        edges=tuple(
            GraphEdge(GraphNodeId(s), GraphNodeId(t), kind) for s, t, kind in edges
        ),
    )


def _dense_graph() -> DependencyGraph:
    """Three nodes joined by every edge type both ways: edges alone exceed 4 * limit."""

    nodes = tuple(
        GraphNode(GraphNodeId(f"n{i}"), GraphNodeType.FILE, f"n{i}", "src/a.py")
        for i in range(3)
    )
    edges = tuple(
        GraphEdge(GraphNodeId(f"n{a}"), GraphNodeId(f"n{b}"), kind)
        for a in range(3)
        for b in range(3)
        if a != b
        for kind in GraphEdgeType
    )
    return DependencyGraph(nodes=nodes, edges=edges)


def _store_with(graph: DependencyGraph):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    organization = Organization(name="Acme")
    repository = Repository(
        organization=organization,
        github_repository_id=1,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    analysis = Analysis(
        repository=repository,
        commit_sha="a" * 40,
        status=AnalysisStatus.COMPLETED,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, analysis])
    session.flush()
    store = SqlAlchemyGraphStore(session)
    store.save_snapshot(
        GraphSnapshot(repository_id=repository.id, analysis_id=analysis.id, graph=graph)
    )
    return store, analysis.id


@pytest.fixture(autouse=True)
def _small_in_lists(monkeypatch):
    import radius_graph.infrastructure.sqlalchemy_store as store_module

    monkeypatch.setattr(store_module, "IN_CHUNK_KEYS", 3)  # exercise the chunking


@pytest.mark.parametrize("graph_seed", range(8))
def test_sql_slice_equals_the_reference_on_random_graphs(graph_seed: int) -> None:
    store, analysis_id = _store_with(_random_graph(graph_seed))
    reference = store.get_snapshot(analysis_id)

    for limit in (1, 2, 5, 12, 1000):
        for seeds in (None, *_SEEDS):
            for depth in (0, 1, 2, 5):
                kwargs = {"limit": limit, "seed_paths": seeds, "depth": depth}
                assert store.get_graph_slice(analysis_id, **kwargs) == slice_snapshot(
                    reference, **kwargs
                ), kwargs


def test_edge_cap_alone_sets_truncated_like_the_reference() -> None:
    store, analysis_id = _store_with(_dense_graph())
    reference = store.get_snapshot(analysis_id)

    for seeds in (None, ("src/a.py",)):
        expected = slice_snapshot(reference, limit=3, seed_paths=seeds)
        actual = store.get_graph_slice(analysis_id, limit=3, seed_paths=seeds)
        assert actual == expected
        assert len(actual.nodes) == 3
        assert len(actual.edges) == 12
        assert actual.truncated is True


def test_truncation_flags_match_on_a_cut_neighbourhood() -> None:
    # One hub with 30 neighbours: the impact slice is cut by the node limit.
    hub = GraphNode(GraphNodeId("hub"), GraphNodeType.FILE, "hub", "src/hub.py")
    leaves = tuple(
        GraphNode(GraphNodeId(f"leaf{i:02d}"), GraphNodeType.FILE, f"leaf{i}", f"l/{i}.py")
        for i in range(30)
    )
    edges = tuple(
        GraphEdge(GraphNodeId(f"leaf{i:02d}"), GraphNodeId("hub"), GraphEdgeType.IMPORTS)
        for i in range(30)
    )
    store, analysis_id = _store_with(
        DependencyGraph(nodes=(hub, *leaves), edges=edges)
    )
    reference = store.get_snapshot(analysis_id)

    for limit, truncated in ((10, True), (31, False)):
        kwargs = {"limit": limit, "seed_paths": ("src/hub.py",), "depth": 3}
        actual = store.get_graph_slice(analysis_id, **kwargs)
        assert actual == slice_snapshot(reference, **kwargs)
        assert actual.truncated is truncated
        assert actual.nodes[0].id.value == "hub"
        assert (actual.node_count, actual.edge_count) == (31, 30)


@pytest.mark.parametrize("graph_seed", range(4))
def test_pages_equal_slices_of_the_stored_order(graph_seed: int) -> None:
    store, analysis_id = _store_with(_random_graph(graph_seed))
    graph = store.get_snapshot(analysis_id).graph

    for limit, offset in ((1, 0), (5, 3), (500, 0), (10, 10_000)):
        nodes = store.list_nodes(analysis_id, limit=limit, offset=offset)
        edges = store.list_edges(analysis_id, limit=limit, offset=offset)
        assert nodes.items == graph.nodes[offset : offset + limit]
        assert edges.items == graph.edges[offset : offset + limit]
        assert (nodes.total, edges.total) == (len(graph.nodes), len(graph.edges))


def test_unknown_analysis_has_no_slice_or_pages() -> None:
    store, _ = _store_with(DependencyGraph())
    missing = uuid4()

    assert store.get_graph_slice(missing, limit=10) is None
    assert store.list_nodes(missing, limit=10) is None
    assert store.list_edges(missing, limit=10) is None


def test_strip_characters_are_exactly_what_str_strip_removes() -> None:
    from radius_graph.infrastructure.sqlalchemy_store import STRIP_CHARACTERS

    expected = "".join(
        char for char in map(chr, range(sys.maxunicode + 1)) if not char.strip()
    )
    assert STRIP_CHARACTERS == expected
