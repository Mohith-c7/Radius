"""Dependency graph API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from radius_graph.dto import GraphSnapshotResponse
from radius_shared.dto import success_response
from radius_shared.errors import NotFoundError

from radius_api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/analyses/{analysis_id}/graph", tags=["graph"])


@router.get("")
def get_graph(
    analysis_id: UUID,
    container: Annotated[AppContainer, Depends(get_container)],
):
    """Return graph metadata and artifact for an analysis."""

    snapshot = container.graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    return success_response(GraphSnapshotResponse.from_entity(snapshot))


@router.get("/nodes")
def get_graph_nodes(
    analysis_id: UUID,
    container: Annotated[AppContainer, Depends(get_container)],
):
    """Return graph nodes for an analysis."""

    snapshot = container.graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    response = GraphSnapshotResponse.from_entity(snapshot)
    return success_response(response.nodes, meta={"count": len(response.nodes)})


@router.get("/edges")
def get_graph_edges(
    analysis_id: UUID,
    container: Annotated[AppContainer, Depends(get_container)],
):
    """Return graph edges for an analysis."""

    snapshot = container.graph_store.get_snapshot(analysis_id)
    if snapshot is None:
        msg = f"Graph snapshot for analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    response = GraphSnapshotResponse.from_entity(snapshot)
    return success_response(response.edges, meta={"count": len(response.edges)})
