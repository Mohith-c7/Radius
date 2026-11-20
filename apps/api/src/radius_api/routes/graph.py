"""Dependency graph API routes."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import AnalysisDetailResponse
from radius_graph.dto import GraphSnapshotResponse
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import success_response
from radius_shared.errors import NotFoundError

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_graph_store,
    get_repository_service,
)

router = APIRouter(prefix="/analyses/{analysis_id}/graph", tags=["graph"])

# A whole-repository graph can be tens of thousands of nodes (megabytes of JSON),
# which proxies such as Vercel refuse to relay. The graph route is bounded.
DEFAULT_GRAPH_NODE_LIMIT = 2000
MAX_GRAPH_NODE_LIMIT = 5000
MAX_IMPACT_DEPTH = 5


@router.get("")
def get_graph(
    analysis_id: UUID,
    *,
    scope: Annotated[
        Literal["full", "impact"],
        Query(
            description=(
                "`full`: the stored graph in stored order. `impact`: nodes on the "
                "analysis' changed files plus their `depth`-hop neighbours."
            ),
        ),
    ] = "full",
    depth: Annotated[
        int,
        Query(
            ge=0, le=MAX_IMPACT_DEPTH, description="Hops from changed files (impact)."
        ),
    ] = 1,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_GRAPH_NODE_LIMIT,
            description="Maximum nodes returned; `truncated` reports a cut.",
        ),
    ] = DEFAULT_GRAPH_NODE_LIMIT,
    graph_store: Annotated[object, Depends(get_graph_store)],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return graph metadata and a bounded slice of the graph for an analysis.

    ``node_count`` / ``edge_count`` are the stored totals; ``returned_*_count``,
    ``scope`` and ``truncated`` describe the slice in ``nodes`` / ``edges``.
    """

    analysis = _ensure_analysis_access(
        analysis_id,
        analysis_service,
        repository_service,
        principal,
    )
    snapshot = graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    seed_paths = (
        [item.path for item in analysis.changed_files] if scope == "impact" else None
    )
    return success_response(
        GraphSnapshotResponse.bounded(
            snapshot,
            limit=limit,
            seed_paths=seed_paths,
            depth=depth,
        )
    )


@router.get("/nodes")
def get_graph_nodes(
    analysis_id: UUID,
    graph_store: Annotated[object, Depends(get_graph_store)],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return graph nodes for an analysis."""

    _ensure_analysis_access(
        analysis_id,
        analysis_service,
        repository_service,
        principal,
    )
    snapshot = graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    response = GraphSnapshotResponse.from_entity(snapshot)
    return success_response(response.nodes, meta={"count": len(response.nodes)})


@router.get("/edges")
def get_graph_edges(
    analysis_id: UUID,
    graph_store: Annotated[object, Depends(get_graph_store)],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return graph edges for an analysis."""

    _ensure_analysis_access(
        analysis_id,
        analysis_service,
        repository_service,
        principal,
    )
    snapshot = graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    response = GraphSnapshotResponse.from_entity(snapshot)
    return success_response(response.edges, meta={"count": len(response.edges)})


def _ensure_analysis_access(
    analysis_id: UUID,
    analysis_service: AnalysisApplicationService,
    repository_service: RepositoryApplicationService,
    principal: ApiPrincipal,
) -> AnalysisDetailResponse:
    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return analysis
