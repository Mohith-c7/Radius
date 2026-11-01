"""Analysis API routes."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import (
    AnalysisListQuery,
    RerunAnalysisCommand,
    StartAnalysisCommand,
)
from radius_repository.application import RepositoryApplicationService
from radius_repository.dto import RepositoryListQuery
from radius_shared.dto import success_response
from radius_shared.errors import NotFoundError, ValidationError

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
from radius_api.schemas.analyses import StartAnalysisRequest

router = APIRouter(prefix="/analyses", tags=["analyses"])

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_analysis(
    http_request: Request,
    request: StartAnalysisRequest,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
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
    """Start a manual analysis run."""

    repository = repository_service.get_repository(request.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    body_hash = await request_hash(http_request)
    existing = replay_or_validate(
        idempotency_store,
        principal.organization_id,
        idempotency_key,
        "start_analysis",
        body_hash,
    )
    if existing is not None:
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
        )

    analysis = service.start_analysis(
        StartAnalysisCommand(
            repository_id=request.repository_id,
            pull_request_id=request.pull_request_id,
            commit_sha=request.commit_sha,
        )
    )
    response = success_response(analysis)
    body = jsonable_encoder(response)
    if idempotency_key is not None:
        idempotency_store.save(
            principal.organization_id,
            idempotency_key,
            "start_analysis",
            body_hash,
            status.HTTP_202_ACCEPTED,
            body,
        )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)


@router.get("")
def list_analyses(
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    repository_id: Annotated[UUID | None, Query(alias="repositoryId")] = None,
    pull_request_id: Annotated[UUID | None, Query(alias="pullRequestId")] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
):
    """List analyses with optional filters."""

    repository_ids = (
        [repository_id]
        if repository_id is not None
        else [
            repository.id
            for repository in repository_service.list_repositories(
                RepositoryListQuery(organization_id=principal.organization_id)
            )
            if repository.id is not None
        ]
    )
    for candidate_repository_id in repository_ids:
        repository = repository_service.get_repository(candidate_repository_id)
        ensure_same_organization(principal, repository.organization_id)

    analyses = []
    for candidate_repository_id in repository_ids:
        analyses.extend(
            service.list_analyses(
                AnalysisListQuery(
                    repository_id=candidate_repository_id,
                    pull_request_id=pull_request_id,
                    status=status_filter,
                )
            )
        )
    return success_response(analyses)


@router.get("/lookup")
def lookup_analysis(
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    pull_request_number: Annotated[int, Query(alias="pullRequest", ge=1)],
    commit_sha: Annotated[str, Query(alias="commitSha")],
    repository: Annotated[
        str | None,
        Query(description="Repository as owner/name (e.g. GITHUB_REPOSITORY)."),
    ] = None,
    repository_id: Annotated[UUID | None, Query(alias="repositoryId")] = None,
):
    """Resolve the newest analysis for a pull request head commit.

    Lets CI find the analysis for ``(repository, PR number, head SHA)``
    without knowing Radius-internal ids. Scoped to the caller's
    organization; returns 404 when Radius has not (yet) created an analysis
    for that commit, so callers can poll.
    """

    if not _COMMIT_SHA.match(commit_sha):
        msg = "commitSha must be 7-64 hexadecimal characters."
        raise ValidationError(msg)
    resolved_repository_id = _resolve_repository_id(
        repository_service,
        principal,
        repository=repository,
        repository_id=repository_id,
    )
    pull_request = repository_service.get_pull_request_by_repository_and_number(
        resolved_repository_id,
        pull_request_number,
    )
    sha = commit_sha.lower()
    candidates = [
        analysis
        for analysis in service.list_analyses(
            AnalysisListQuery(
                repository_id=resolved_repository_id,
                pull_request_id=pull_request.id,
            )
        )
        if analysis.commit_sha.lower() == sha
        or (len(sha) < 40 and analysis.commit_sha.lower().startswith(sha))
    ]
    if not candidates:
        msg = (
            f"No analysis found for pull request #{pull_request_number} at commit "
            f"{sha[:12]}."
        )
        raise NotFoundError(msg)
    newest = max(candidates, key=lambda item: item.created_at)
    return success_response(newest)


def _resolve_repository_id(
    repository_service: RepositoryApplicationService,
    principal: ApiPrincipal,
    *,
    repository: str | None,
    repository_id: UUID | None,
) -> UUID:
    if repository_id is not None:
        found = repository_service.get_repository(repository_id)
        ensure_same_organization(principal, found.organization_id)
        return repository_id
    if not repository or repository.count("/") != 1:
        msg = "Pass repository=owner/name or repositoryId."
        raise ValidationError(msg)
    owner, name = (part.strip().lower() for part in repository.split("/"))
    for candidate in repository_service.list_repositories(
        RepositoryListQuery(organization_id=principal.organization_id)
    ):
        if (
            candidate.id is not None
            and candidate.owner.lower() == owner
            and candidate.name.lower() == name
        ):
            return candidate.id
    msg = f"Repository {repository} is not connected to this organization."
    raise NotFoundError(msg)


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return one analysis."""

    analysis = service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(analysis)


@router.post("/{analysis_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
async def rerun_analysis(
    http_request: Request,
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
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
    """Create a new analysis from an existing one."""

    existing_analysis = service.get_analysis(analysis_id)
    repository = repository_service.get_repository(existing_analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    body_hash = await request_hash(http_request)
    scope = f"rerun_analysis:{analysis_id}"
    existing = replay_or_validate(
        idempotency_store,
        principal.organization_id,
        idempotency_key,
        scope,
        body_hash,
    )
    if existing is not None:
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
        )

    response = success_response(
        service.rerun_analysis(RerunAnalysisCommand(analysis_id=analysis_id))
    )
    body = jsonable_encoder(response)
    if idempotency_key is not None:
        idempotency_store.save(
            principal.organization_id,
            idempotency_key,
            scope,
            body_hash,
            status.HTTP_202_ACCEPTED,
            body,
        )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)


@router.get("/{analysis_id}/blast-radius")
def get_blast_radius(
    analysis_id: UUID,
    service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Return blast-radius summary for an analysis."""

    analysis = service.get_analysis(analysis_id)
    repository = repository_service.get_repository(analysis.repository_id)
    ensure_same_organization(principal, repository.organization_id)
    return success_response(service.get_blast_radius(analysis_id))
