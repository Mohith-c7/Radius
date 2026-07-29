"""Repository API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import RepositoryVisibility
from radius_repository.dto import ConnectRepositoryCommand, RepositoryListQuery
from radius_shared.dto import success_response

from radius_api.dependencies import get_repository_service
from radius_api.schemas.repositories import ConnectRepositoryRequest

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("", status_code=status.HTTP_201_CREATED)
def connect_repository(
    request: ConnectRepositoryRequest,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
):
    """Connect a repository to Radius."""

    repository = service.connect_repository(
        ConnectRepositoryCommand(
            organization_id=request.organization_id,
            github_repository_id=request.github_repository_id,
            name=request.name,
            owner=request.owner,
            default_branch=request.default_branch,
            clone_url=request.clone_url,
            visibility=RepositoryVisibility(request.visibility),
        )
    )
    return success_response(repository)


@router.get("")
def list_repositories(
    organization_id: Annotated[UUID, Query(alias="organizationId")],
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    visibility: str | None = None,
):
    """List repositories for an organization."""

    repositories = service.list_repositories(
        RepositoryListQuery(
            organization_id=organization_id,
            status=status_filter,
            visibility=visibility,
        )
    )
    return success_response(repositories)


@router.get("/{repository_id}")
def get_repository(
    repository_id: UUID,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
):
    """Return one repository."""

    return success_response(service.get_repository(repository_id))


@router.delete("/{repository_id}")
def disconnect_repository(
    repository_id: UUID,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
):
    """Disconnect one repository."""

    return success_response(service.disconnect_repository(repository_id))
