"""Dependency graph API routes."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import AnalysisDetailResponse
from radius_graph.dto import (
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphSnapshotResponse,
)
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import success_response
from radius_shared.errors import NotFoundError

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_graph_store,
    get_repository_service,
)
from radius_api.pagination import MAX_OFFSET

router = APIRouter(prefix="/analyses/{analysis_id}/graph", tags=["graph"])

# A whole-repository graph can be tens of thousands of nodes (megabytes of JSON),
# which proxies such as Vercel refuse to relay. Every graph route is bounded, and
# the store computes the slice or page in SQL: materialising the whole snapshot
# cost seconds of CPU on a 0.1-CPU host and starved the health check.
DEFAULT_GRAPH_NODE_LIMIT = 2000
MAX_GRAPH_NODE_LIMIT = 5000
MAX_IMPACT_DEPTH = 5
DEFAULT_GRAPH_PAGE_LIMIT = 500

GraphPageLimit = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_GRAPH_NODE_LIMIT,
        description=f"Page size (default {DEFAULT_GRAPH_PAGE_LIMIT}, max {MAX_GRAPH_NODE_LIMIT}).",
    ),
]
GraphPageOffset = Annotated[
    int, Query(ge=0, le=MAX_OFFSET, description="Items to skip.")
]


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
    seed_paths = (
        [item.path for item in analysis.changed_files] if scope == "impact" else None
    )
    graph_slice = graph_store.get_graph_slice(
        analysis_id,
        limit=limit,
        seed_paths=seed_paths,
        depth=depth,
    )
    if graph_slice is None:
        raise NotFoundError(_not_found(analysis_id))
    return success_response(GraphSnapshotResponse.from_slice(graph_slice))


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
    limit: GraphPageLimit = DEFAULT_GRAPH_PAGE_LIMIT,
    offset: GraphPageOffset = 0,
):
    """Return one page of graph nodes for an analysis, in stored order.

    ``meta.count`` is the number returned and ``meta.pagination`` holds
    ``limit``, ``offset``, ``total`` and ``returned``.
    """

    _ensure_analysis_access(
        analysis_id,
        analysis_service,
        repository_service,
        principal,
    )
    page = graph_store.list_nodes(analysis_id, limit=limit, offset=offset)
    if page is None:
        raise NotFoundError(_not_found(analysis_id))
    items = [GraphNodeResponse.from_entity(item) for item in page.items]
    return success_response(items, meta=_page_meta(page.total, len(items), limit, offset))


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
    limit: GraphPageLimit = DEFAULT_GRAPH_PAGE_LIMIT,
    offset: GraphPageOffset = 0,
):
    """Return one page of graph edges for an analysis, in stored order.

    ``meta.count`` is the number returned and ``meta.pagination`` holds
    ``limit``, ``offset``, ``total`` and ``returned``.
    """

    _ensure_analysis_access(
        analysis_id,
        analysis_service,
        repository_service,
        principal,
    )
    page = graph_store.list_edges(analysis_id, limit=limit, offset=offset)
    if page is None:
        raise NotFoundError(_not_found(analysis_id))
    items = [GraphEdgeResponse.from_entity(item) for item in page.items]
    return success_response(items, meta=_page_meta(page.total, len(items), limit, offset))


def _not_found(analysis_id: UUID) -> str:
    return f"Graph snapshot for analysis {analysis_id} was not found."


def _page_meta(total: int, returned: int, limit: int, offset: int) -> dict[str, object]:
    return {
        "count": returned,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "returned": returned,
        },
    }


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
