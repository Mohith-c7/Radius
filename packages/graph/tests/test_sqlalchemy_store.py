"""SQLAlchemy graph store tests."""

from datetime import UTC, datetime
from uuid import uuid4

from radius_graph.domain import (
    DependencyGraph,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphSnapshot,
)
from radius_graph.infrastructure import SqlAlchemyGraphStore
from radius_shared.database.base import Base
from radius_shared.database.enums import (
    AnalysisStatus,
    PullRequestStatus,
    RepositoryVisibility,
)
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_graph_store_persists_nodes_and_edges() -> None:
    with _session() as session:
        repository_id, analysis_id = _create_context(session)
        store = SqlAlchemyGraphStore(session)
        snapshot = GraphSnapshot(
            repository_id=repository_id,
            analysis_id=analysis_id,
            graph=DependencyGraph(
                nodes=(
                    GraphNode(
                        GraphNodeId("file:src/core.py"),
                        GraphNodeType.FILE,
                        "src/core.py",
                        "src/core.py",
                    ),
                    GraphNode(
                        GraphNodeId("file:src/api.py"),
                        GraphNodeType.FILE,
                        "src/api.py",
                        "src/api.py",
                    ),
                ),
                edges=(
                    GraphEdge(
                        GraphNodeId("file:src/api.py"),
                        GraphNodeId("file:src/core.py"),
                        GraphEdgeType.DEPENDS_ON,
                    ),
                ),
            ),
        )

        store.save_snapshot(snapshot)
        loaded = store.get_snapshot(analysis_id)

        assert loaded.node_count == 2
        assert loaded.edge_count == 1
        assert loaded.graph.edges[0].edge_type == GraphEdgeType.DEPENDS_ON


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_context(session: Session):
    organization = Organization(name="Acme")
    repository = Repository(
        organization=organization,
        github_repository_id=uuid4().int % 100000,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=42,
        title="Graph",
        source_branch="feature",
        target_branch="main",
        author="mohith",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    analysis = Analysis(
        repository=repository,
        pull_request=pull_request,
        commit_sha="a" * 40,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, pull_request, analysis])
    session.flush()
    return repository.id, analysis.id
