"""The analysis graph route returns a bounded slice (scope / depth / limit)."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_analysis.dto import ChangedFileInput, RecordChangedFilesCommand
from radius_api.main import create_app
from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphSnapshot,
)


def _file(path: str) -> GraphNode:
    return GraphNode(GraphNodeId(f"file:{path}"), GraphNodeType.FILE, path, path)


def _edge(source: str, target: str) -> GraphEdge:
    return GraphEdge(
        GraphNodeId(f"file:{source}"),
        GraphNodeId(f"file:{target}"),
        GraphEdgeType.IMPORTS,
    )


# a -> b -> c -> d, plus e isolated: 5 nodes, 3 edges.
_GRAPH = DependencyGraph(
    nodes=tuple(_file(f"src/{name}.py") for name in "abcde"),
    edges=(
        _edge("src/a.py", "src/b.py"),
        _edge("src/b.py", "src/c.py"),
        _edge("src/c.py", "src/d.py"),
    ),
)


def _setup(changed_paths: tuple[str, ...] = ("src/b.py",)):
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": organization_id}
    repository_id = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": organization_id,
            "repositoryId": 404,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    analysis_id = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": repository_id,
            "commitSha": "d" * 40,
        },
    ).json()["data"]["id"]
    container = app.state.container
    container.analysis_service().record_changed_files(
        RecordChangedFilesCommand(
            analysis_id=UUID(analysis_id),
            changed_files=tuple(
                ChangedFileInput(path=path, change_type="modified")
                for path in changed_paths
            ),
        )
    )
    container.graph_store.save_snapshot(
        GraphSnapshot(
            repository_id=UUID(repository_id),
            analysis_id=UUID(analysis_id),
            graph=_GRAPH,
        )
    )
    return client, headers, f"/api/v1/analyses/{analysis_id}/graph"


def _ids(data: dict) -> list[str]:
    return [node["id"] for node in data["nodes"]]


def test_default_request_is_the_full_graph_when_under_the_limit() -> None:
    client, headers, url = _setup()

    data = client.get(url, headers=headers).json()["data"]

    assert data["scope"] == "full"
    assert data["truncated"] is False
    assert (data["node_count"], data["edge_count"]) == (5, 3)
    assert (data["returned_node_count"], data["returned_edge_count"]) == (5, 3)
    assert len(data["nodes"]) == 5
    assert len(data["edges"]) == 3


def test_limit_truncates_nodes_keeps_totals_and_drops_dangling_edges() -> None:
    client, headers, url = _setup()

    data = client.get(url, headers=headers, params={"limit": 2}).json()["data"]

    assert data["truncated"] is True
    assert (data["node_count"], data["edge_count"]) == (5, 3)
    assert _ids(data) == ["file:src/a.py", "file:src/b.py"]
    assert data["edges"] == [
        {
            "source_id": "file:src/a.py",
            "target_id": "file:src/b.py",
            "edge_type": "imports",
        }
    ]
    assert (data["returned_node_count"], data["returned_edge_count"]) == (2, 1)


def test_impact_scope_returns_changed_files_and_neighbours_nearest_first() -> None:
    client, headers, url = _setup(changed_paths=("src/b.py",))

    one_hop = client.get(url, headers=headers, params={"scope": "impact"}).json()[
        "data"
    ]
    two_hops = client.get(
        url, headers=headers, params={"scope": "impact", "depth": 2}
    ).json()["data"]
    seeds_only = client.get(
        url, headers=headers, params={"scope": "impact", "depth": 0}
    ).json()["data"]
    capped = client.get(
        url, headers=headers, params={"scope": "impact", "depth": 2, "limit": 1}
    ).json()["data"]

    assert one_hop["scope"] == "impact"
    assert one_hop["truncated"] is False
    assert one_hop["node_count"] == 5
    assert _ids(one_hop) == ["file:src/b.py", "file:src/a.py", "file:src/c.py"]
    assert one_hop["returned_edge_count"] == 2
    assert _ids(two_hops) == [
        "file:src/b.py",
        "file:src/a.py",
        "file:src/c.py",
        "file:src/d.py",
    ]
    assert _ids(seeds_only) == ["file:src/b.py"]
    assert _ids(capped) == ["file:src/b.py"]
    assert capped["truncated"] is True


def test_impact_scope_without_changed_files_is_empty() -> None:
    client, headers, url = _setup(changed_paths=())

    data = client.get(url, headers=headers, params={"scope": "impact"}).json()["data"]

    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["node_count"] == 5
    assert data["truncated"] is False


def test_out_of_range_parameters_are_rejected() -> None:
    client, headers, url = _setup()

    assert client.get(url, headers=headers, params={"limit": 5001}).status_code == 422
    assert client.get(url, headers=headers, params={"limit": 0}).status_code == 422
    assert client.get(url, headers=headers, params={"depth": 6}).status_code == 422
    assert client.get(url, headers=headers, params={"scope": "all"}).status_code == 422


def test_other_organization_still_cannot_read_the_graph() -> None:
    client, _, url = _setup()
    other = {"X-Radius-Organization-Id": str(uuid4())}

    for params in ({}, {"scope": "impact"}, {"scope": "full", "limit": 1}):
        response = client.get(url, headers=other, params=params)
        assert response.status_code == 403
        assert "data" not in response.json() or response.json()["data"] is None
