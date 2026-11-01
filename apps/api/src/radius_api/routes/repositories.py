"""Repository API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import RepositoryVisibility
from radius_repository.dto import ConnectRepositoryCommand, RepositoryListQuery
from radius_shared.dto import success_response

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_idempotency_store,
    get_repository_service,
)
from radius_api.idempotency import (
    IdempotencyStore,
    replay_or_validate,
    request_hash,
)
from radius_api.schemas.repositories import (
    ConnectRepositoryRequest,
    UpdateRepositoryRequest,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def connect_repository(
    http_request: Request,
    request: ConnectRepositoryRequest,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    idempotency_store: Annotated[
        IdempotencyStore,
        Depends(get_idempotency_store),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Connect a repository to Radius."""

    ensure_same_organization(principal, request.organization_id)
    body_hash = await request_hash(http_request)
    existing = replay_or_validate(
        idempotency_store,
        principal.organization_id,
        idempotency_key,
        "connect_repository",
        body_hash,
    )
    if existing is not None:
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
        )

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
    response = success_response(repository)
    body = jsonable_encoder(response)
    if idempotency_key is not None:
        idempotency_store.save(
            principal.organization_id,
            idempotency_key,
            "connect_repository",
            body_hash,
            status.HTTP_201_CREATED,
            body,
        )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=body)


@router.get("")
def list_repositories(
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    organization_id: Annotated[UUID | None, Query(alias="organizationId")] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    visibility: str | None = None,
):
    """List repositories for an organization."""

    if organization_id is not None:
        ensure_same_organization(principal, organization_id)
    repositories = service.list_repositories(
        RepositoryListQuery(
            organization_id=principal.organization_id,
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
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return one repository."""

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(repository)


@router.delete("/{repository_id}")
def disconnect_repository(
    repository_id: UUID,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Disconnect one repository."""

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(service.disconnect_repository(repository_id))


@router.patch("/{repository_id}")
def update_repository(
    repository_id: UUID,
    payload: UpdateRepositoryRequest,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Update repository configuration such as default branch."""

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    updated = service.update_default_branch(repository_id, payload.default_branch)
    return success_response(updated)


@router.get("/{repository_id}/pull-requests/{github_pr_number}")
def get_pull_request_by_number(
    repository_id: UUID,
    github_pr_number: int,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return a pull request by repository ID and GitHub PR number."""

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    pull_request = service.get_pull_request_by_repository_and_number(
        repository_id, github_pr_number
    )
    return success_response(pull_request)


@router.get("/{repository_id}/pull-requests")
def list_pull_requests(
    repository_id: UUID,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """List all pull requests for one repository."""

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    pull_requests = service.list_pull_requests(repository_id)
    return success_response(pull_requests)


@router.post("/{repository_id}/sync-pull-requests")
def sync_pull_requests(
    http_request: Request,
    repository_id: UUID,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    auto_analyze: bool = Query(default=True),
):
    """Sync open pull requests from GitHub and optionally trigger automatic scoring."""

    from datetime import UTC, datetime

    from radius_analysis.dto import StartAnalysisCommand
    from radius_github import GitHubAppClient, GitHubAppSettings
    from radius_repository.dto import UpsertPullRequestCommand

    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)

    settings = GitHubAppSettings()
    synced_prs = []
    if settings.enabled:
        client = GitHubAppClient(settings)
        installation_id = settings.github_installation_id or 0
        if not installation_id:
            session = getattr(http_request.state, "radius_db_session", None)
            if session is not None:
                from radius_database import models as db_models
                org = session.get(db_models.Organization, repository.organization_id)
                if org and org.github_installation_id:
                    installation_id = org.github_installation_id

        if installation_id:
            try:
                token = client.create_installation_token(installation_id).token
                gh_prs = client.list_pull_requests(
                    token=token,
                    owner=repository.owner,
                    repo=repository.name,
                    state="open",
                )
                for pr in gh_prs:
                    pr_num = pr.get("number")
                    head = pr.get("head", {})
                    base = pr.get("base", {})
                    user = pr.get("user", {})
                    opened_at_str = pr.get("created_at")
                    opened_at = (
                        datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
                        if opened_at_str
                        else datetime.now(UTC)
                    )
                    upserted = service.upsert_pull_request(
                        UpsertPullRequestCommand(
                            repository_id=repository_id,
                            github_pr_number=pr_num,
                            title=pr.get("title", f"PR #{pr_num}"),
                            source_branch=head.get("ref", "unknown"),
                            target_branch=base.get("ref", repository.default_branch),
                            author=user.get("login", "unknown"),
                            status="open",
                            opened_at=opened_at,
                        )
                    )
                    synced_prs.append(upserted)

                    # Trigger automatic scoring engine if auto_analyze is enabled
                    if auto_analyze and head.get("sha"):
                        analysis_service.start_analysis(
                            StartAnalysisCommand(
                                repository_id=repository_id,
                                pull_request_id=upserted.id,
                                commit_sha=head["sha"],
                            )
                        )
            except Exception:
                pass

    if not synced_prs:
        synced_prs = service.list_pull_requests(repository_id)

    return success_response(synced_prs)
