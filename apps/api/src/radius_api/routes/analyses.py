"""Analysis API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import (
    AnalysisListQuery,
    RerunAnalysisCommand,
    StartAnalysisCommand,
)
from radius_shared.dto import success_response

from radius_api.dependencies import get_analysis_service
from radius_api.schemas.analyses import StartAnalysisRequest

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_analysis(
    request: StartAnalysisRequest,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
):
    """Start a manual analysis run."""

    analysis = service.start_analysis(
        StartAnalysisCommand(
            repository_id=request.repository_id,
            pull_request_id=request.pull_request_id,
            commit_sha=request.commit_sha,
        )
    )
    return success_response(analysis)


@router.get("")
def list_analyses(
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_id: Annotated[UUID | None, Query(alias="repositoryId")] = None,
    pull_request_id: Annotated[UUID | None, Query(alias="pullRequestId")] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
):
    """List analyses with optional filters."""

    analyses = service.list_analyses(
        AnalysisListQuery(
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            status=status_filter,
        )
    )
    return success_response(analyses)


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
):
    """Return one analysis."""

    return success_response(service.get_analysis(analysis_id))


@router.post("/{analysis_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def rerun_analysis(
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
):
    """Create a new analysis from an existing one."""

    return success_response(
        service.rerun_analysis(RerunAnalysisCommand(analysis_id=analysis_id))
    )


@router.get("/{analysis_id}/blast-radius")
def get_blast_radius(
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
):
    """Return blast-radius summary for an analysis."""

    return success_response(service.get_blast_radius(analysis_id))
