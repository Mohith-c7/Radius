"""Shared tenant-ownership dependencies for routes keyed by an analysis id."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from radius_analysis.application import AnalysisApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_shared.errors import NotFoundError

from radius_api.auth import ApiPrincipal, get_api_principal
from radius_api.dependencies import get_analysis_service, get_repository_service


def resolve_owned_analysis(
    analysis_id: UUID,
    principal: ApiPrincipal,
    analysis_service: AnalysisApplicationService,
    repository_service: RepositoryApplicationService,
) -> UUID:
    """Return ``analysis_id`` when its repository belongs to the caller's organization.

    Unknown analyses and analyses of other organizations are indistinguishable
    (both 404), so ids of other tenants cannot be probed.
    """

    missing = NotFoundError("Analysis not found.", code="ANALYSIS_NOT_FOUND")
    try:
        analysis = analysis_service.get_analysis(analysis_id)
        repository = repository_service.get_repository(analysis.repository_id)
    except NotFoundError:
        raise missing from None
    if repository.organization_id != principal.organization_id:
        raise missing
    return analysis_id


def get_owned_analysis_id(
    analysis_id: UUID,
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    analysis_service: Annotated[
        AnalysisApplicationService, Depends(get_analysis_service)
    ],
    repository_service: Annotated[
        RepositoryApplicationService, Depends(get_repository_service)
    ],
) -> UUID:
    """FastAPI dependency for ``/.../{analysis_id}`` path parameters."""

    return resolve_owned_analysis(
        analysis_id, principal, analysis_service, repository_service
    )


OwnedAnalysisId = Annotated[UUID, Depends(get_owned_analysis_id)]
