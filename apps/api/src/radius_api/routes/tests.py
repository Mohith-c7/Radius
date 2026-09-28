"""Test selection API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from radius_analysis.application import AnalysisApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import success_response
from radius_testing.application import TestingApplicationService

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_repository_service,
    get_testing_service,
)

router = APIRouter(prefix="/analyses/{analysis_id}/tests", tags=["tests"])


@router.get("")
def get_selected_tests(
    analysis_id: UUID,
    service: Annotated[
        TestingApplicationService,
        Depends(get_testing_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    format: str | None = Query(None),
):
    """Return selected tests for an analysis."""

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    selection = service.get_selection(analysis_id)
    if format == "cli":
        return PlainTextResponse(selection.cli_args)
    return success_response(selection)

