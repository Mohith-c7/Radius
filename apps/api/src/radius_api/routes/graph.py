"""Dependency graph API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from radius_analysis.application import AnalysisApplicationService
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


@router.get("")
def get_graph(
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
    """Return graph metadata and artifact for an analysis."""

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
    return success_response(GraphSnapshotResponse.from_entity(snapshot))


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
) -> None:
    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
