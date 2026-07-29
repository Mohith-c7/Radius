"""Confidence API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from radius_analysis.application import AnalysisApplicationService
from radius_confidence.application import ConfidenceApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.dto import success_response

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_confidence_service,
    get_repository_service,
)

router = APIRouter(prefix="/analyses/{analysis_id}/confidence", tags=["confidence"])


@router.get("")
def get_confidence(
    analysis_id: UUID,
    service: Annotated[
        ConfidenceApplicationService,
        Depends(get_confidence_service),
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
):
    """Return confidence report for an analysis."""

    analysis = analysis_service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(service.get_report(analysis_id))
