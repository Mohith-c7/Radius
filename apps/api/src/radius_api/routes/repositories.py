"""Repository API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import AnalysisListQuery, StartAnalysisCommand
from radius_github import GitHubAppClient
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import RepositoryVisibility
from radius_repository.dto import (
    ConnectRepositoryCommand,
    RepositoryListQuery,
    UpsertPullRequestCommand,
)
from radius_shared.dto import success_response
from radius_shared.errors import AccessDeniedError, ConflictError, RadiusError

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_github_client,
    get_idempotency_store,
    get_repository_service,
)
from radius_api.github_intent import record_pull_request_intent
from radius_api.github_pull import (
    open_access,
    parse_owner_repo,
    parse_pull_request,
    pull_request_status,
    require_configured,
    translate_github_error,
)
from radius_api.idempotency import (
    IdempotencyStore,
    replay_or_validate,
    request_hash,
)
from radius_api.schemas.repositories import (
    ConnectGitHubRepositoryRequest,
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


@router.post("/connect-github", status_code=status.HTTP_201_CREATED)
def connect_github_repository(
    http_request: Request,
    payload: ConnectGitHubRepositoryRequest,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    github: Annotated[GitHubAppClient, Depends(get_github_client)],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Connect a repository by ``owner/name`` through the GitHub App (no webhook).

    The API asks GitHub which App installation covers the repository, reads the
    repository metadata (id, default branch, clone URL, visibility) and stores
    the installation id on the organization, which is all the worker needs to
    clone, analyze and publish. Safe to repeat: an already connected repository
    is returned (and reconnected if it had been disconnected).
    """

    owner, name = parse_owner_repo(payload.repository)
    access = open_access(
        http_request,
        github,
        organization_id=principal.organization_id,
        owner=owner,
        repo=name,
        discover=True,
    )
    try:
        info = github.get_repository(token=access.token, owner=owner, repo=name)
    except Exception as exc:  # noqa: BLE001
        raise translate_github_error(
            exc, what=f"reading repository {owner}/{name}"
        ) from exc
    github_id = info.get("id")
    clone_url = info.get("clone_url")
    if not isinstance(github_id, int) or not clone_url:
        raise ConflictError(
            f"GitHub returned incomplete metadata for {owner}/{name}.",
            code="GITHUB_API_ERROR",
        )
    default_branch = str(info.get("default_branch") or "main")
    meta = {"installationId": access.installation_id}
    existing = service.get_by_github_repository_id(github_id)
    if existing is not None:
        if existing.organization_id != principal.organization_id:
            raise AccessDeniedError(
                "GitHub repository is already connected to another organization."
            )
        repository_id = UUID(str(existing.id))
        if existing.status == "disconnected":
            service.reconnect_repository(repository_id)
        if existing.default_branch != default_branch:
            service.update_default_branch(repository_id, default_branch)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(
                success_response(
                    service.get_repository(repository_id),
                    meta={**meta, "created": False},
                )
            ),
        )
    repository = service.connect_repository(
        ConnectRepositoryCommand(
            organization_id=principal.organization_id,
            github_repository_id=github_id,
            name=str(info.get("name") or name),
            owner=str((info.get("owner") or {}).get("login") or owner),
            default_branch=default_branch,
            clone_url=str(clone_url),
            visibility=(
                RepositoryVisibility.PRIVATE
                if info.get("private", True)
                else RepositoryVisibility.PUBLIC
            ),
        )
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=jsonable_encoder(
            success_response(repository, meta={**meta, "created": True})
        ),
    )


def _record_and_analyze(
    http_request: Request,
    *,
    service: RepositoryApplicationService,
    analysis_service: AnalysisApplicationService,
    repository,
    raw_pull_request: dict,
    principal: ApiPrincipal,
    analyze: bool,
    skip_analyzed: bool = False,
):
    """Upsert one GitHub pull request; start an analysis for its head commit."""

    pull_request = parse_pull_request(raw_pull_request)
    upserted = service.upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(str(repository.id)),
            github_pr_number=pull_request.number,
            title=pull_request.title,
            source_branch=pull_request.head.ref,
            target_branch=pull_request.base.ref,
            author=pull_request.user.login,
            status=pull_request_status(pull_request),
            opened_at=pull_request.created_at,
            merged_at=pull_request.merged_at,
        )
    )
    analysis = None
    if analyze and pull_request.head.sha and skip_analyzed and _already_analyzed(
        analysis_service, UUID(str(repository.id)), UUID(str(upserted.id)), pull_request.head.sha
    ):
        analyze = False
    if analyze and pull_request.head.sha:
        analysis = analysis_service.start_analysis(
            StartAnalysisCommand(
                repository_id=UUID(str(repository.id)),
                pull_request_id=UUID(str(upserted.id)),
                commit_sha=pull_request.head.sha,
            )
        )
        if getattr(http_request.state, "radius_webhook_org_id", None) is None:
            http_request.state.radius_webhook_org_id = principal.organization_id
        record_pull_request_intent(
            http_request,
            analysis_id=UUID(str(analysis.id)),
            payload=pull_request,
            owner=repository.owner,
            repo=repository.name,
            trigger="pull_request.pull",
        )
    return upserted, analysis


def _skip_reason(exc: Exception) -> str:
    """Short, secret-free reason a pull request was skipped during a sync."""

    if isinstance(exc, RadiusError):
        return f"{exc.detail.code}: {exc.detail.message}"[:200]
    return type(exc).__name__


def _already_analyzed(
    analysis_service: AnalysisApplicationService,
    repository_id: UUID,
    pull_request_id: UUID,
    commit_sha: str,
) -> bool:
    """True when this head commit has a live or finished analysis (repeat syncs are no-ops)."""

    return any(
        analysis.commit_sha.lower() == commit_sha.lower()
        and analysis.status not in ("failed", "cancelled")
        for analysis in analysis_service.list_analyses(
            AnalysisListQuery(repository_id=repository_id, pull_request_id=pull_request_id)
        )
    )


def _connected_repository(
    service: RepositoryApplicationService,
    principal: ApiPrincipal,
    repository_id: UUID,
):
    repository = service.get_repository(repository_id)
    ensure_same_organization(principal, repository.organization_id)
    if repository.status == "disconnected":
        raise ConflictError(
            "Repository is disconnected. Connect it again first.",
            code="REPOSITORY_DISCONNECTED",
        )
    return repository


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
    github: Annotated[GitHubAppClient, Depends(get_github_client)],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    auto_analyze: bool = Query(default=True),
):
    """Pull open pull requests from GitHub (no webhook) and analyze them.

    Draft pull requests are stored but not analyzed, and a head commit that already
    has a live or finished analysis is not analyzed again (repeat syncs are cheap);
    use the per-PR ``analyze`` route to analyze one explicitly. Without GitHub App credentials the stored
    pull requests are returned unchanged (``meta.github = not_configured``).
    GitHub failures are returned as errors, not swallowed.
    """

    repository = _connected_repository(service, principal, repository_id)
    if not github.settings.enabled:
        return success_response(
            service.list_pull_requests(repository_id),
            meta={"github": "not_configured"},
        )
    access = open_access(
        http_request,
        github,
        organization_id=principal.organization_id,
        owner=repository.owner,
        repo=repository.name,
    )
    try:
        raw_pull_requests = github.list_pull_requests(
            token=access.token,
            owner=repository.owner,
            repo=repository.name,
            state="open",
        )
    except Exception as exc:  # noqa: BLE001
        raise translate_github_error(
            exc, what=f"listing pull requests of {repository.owner}/{repository.name}"
        ) from exc

    synced = []
    analyses: list[str] = []
    skipped: list[dict[str, object]] = []
    for raw in raw_pull_requests:
        number = raw.get("number")
        analyze = bool(auto_analyze and not raw.get("draft"))
        try:
            upserted, analysis = _record_and_analyze(
                http_request,
                service=service,
                analysis_service=analysis_service,
                repository=repository,
                raw_pull_request=raw,
                principal=principal,
                analyze=analyze,
                skip_analyzed=True,
            )
        except Exception as exc:  # noqa: BLE001 - one bad PR must not stop the sync
            skipped.append({"number": number, "reason": _skip_reason(exc)})
            continue
        synced.append(upserted)
        if analysis is not None:
            analyses.append(str(analysis.id))
    return success_response(
        synced,
        meta={
            "github": "synced",
            "installationId": access.installation_id,
            "analysisIds": analyses,
            "skipped": skipped,
        },
    )


@router.post(
    "/{repository_id}/pull-requests/{github_pr_number}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_pull_request(
    http_request: Request,
    repository_id: UUID,
    github_pr_number: int,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    github: Annotated[GitHubAppClient, Depends(get_github_client)],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Analyze one pull request by number: fetch it from GitHub, queue an analysis.

    This is the pull-based replacement for the ``pull_request`` webhook. The head
    commit is read from GitHub, so the caller does not need a commit SHA. A
    pending or running analysis of the same head commit is reused.
    """

    repository = _connected_repository(service, principal, repository_id)
    require_configured(github)
    access = open_access(
        http_request,
        github,
        organization_id=principal.organization_id,
        owner=repository.owner,
        repo=repository.name,
    )
    try:
        raw = github.get_pull_request(
            token=access.token,
            owner=repository.owner,
            repo=repository.name,
            number=github_pr_number,
        )
    except Exception as exc:  # noqa: BLE001
        raise translate_github_error(
            exc,
            what=(
                f"reading pull request #{github_pr_number} of "
                f"{repository.owner}/{repository.name}"
            ),
        ) from exc
    upserted, analysis = _record_and_analyze(
        http_request,
        service=service,
        analysis_service=analysis_service,
        repository=repository,
        raw_pull_request=raw,
        principal=principal,
        analyze=True,
    )
    return success_response(
        analysis,
        meta={
            "pullRequestId": str(upserted.id),
            "installationId": access.installation_id,
        },
    )
