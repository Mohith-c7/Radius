"""Repository API routes."""

import os
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_github import GitHubAppClient
from radius_github.pull_sync import record_pull_request, sync_open_pull_requests
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import RepositoryVisibility
from radius_repository.domain.clone_url import validate_clone_url
from radius_repository.dto import (
    ConnectRepositoryCommand,
    RepositoryListQuery,
)
from radius_shared.dto import success_response
from radius_shared.errors import ConflictError, NotFoundError

from radius_api.auth import ApiPrincipal, ensure_same_organization, get_api_principal
from radius_api.dependencies import (
    get_analysis_service,
    get_github_client,
    get_idempotency_store,
    get_repository_service,
)
from radius_api.github_intent import record_pull_request_intent
from radius_api.github_pull import (
    clone_policy,
    open_access,
    parse_owner_repo,
    parse_pull_request,
    require_configured,
    translate_github_error,
)
from radius_api.idempotency import (
    IdempotencyStore,
    replay_or_validate,
    request_hash,
)
from radius_api.pagination import PageParams
from radius_api.schemas.repositories import (
    ConnectGitHubRepositoryRequest,
    ConnectRepositoryRequest,
    ImportPullRequestRequest,
    UpdateRepositoryRequest,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _owned_repository(
    service: RepositoryApplicationService,
    principal: ApiPrincipal,
    repository_id: UUID,
):
    """Return the repository when it belongs to the caller's organization.

    An unknown id and another organization's repository are indistinguishable
    (both 404), so repository ids cannot be probed across tenants.
    """

    try:
        repository = service.get_repository(repository_id)
    except NotFoundError:
        raise NotFoundError(f"Repository {repository_id} was not found.") from None
    if repository.organization_id != principal.organization_id:
        raise NotFoundError(f"Repository {repository_id} was not found.")
    return repository


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
    # A-01/A-02: the clone URL ends up as an argument of ``git``. Accept only
    # https://<allowed host>/<owner>/<repo>[.git]; the stored value is canonical.
    clone_url = validate_clone_url(request.clone_url, policy=clone_policy(http_request))
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
            clone_url=clone_url,
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
    page: PageParams,
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
    window = page.slice(repositories)
    return success_response(
        window, meta=page.meta(total=len(repositories), returned=len(window))
    )


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

    repository = _owned_repository(service, principal, repository_id)
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

    _owned_repository(service, principal, repository_id)
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

    _owned_repository(service, principal, repository_id)
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

    _owned_repository(service, principal, repository_id)
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
    page: PageParams,
):
    """List the pull requests of one repository, newest first (``limit``/``offset``)."""

    _owned_repository(service, principal, repository_id)
    pull_requests = service.list_pull_requests(repository_id)
    window = page.slice(pull_requests)
    return success_response(
        window, meta=page.meta(total=len(pull_requests), returned=len(window))
    )


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
    # GitHub's own metadata is still checked: the URL must be https on an
    # allowed host and name the repository we were asked about.
    clone_url = validate_clone_url(clone_url, policy=clone_policy(http_request))
    default_branch = str(info.get("default_branch") or "main")
    meta = {"installationId": access.installation_id}
    existing = service.get_by_github_repository_id(github_id)
    if existing is not None:
        if existing.organization_id != principal.organization_id:
            raise ConflictError(
                "This repository cannot be connected.",
                code="REPOSITORY_ALREADY_CONNECTED",
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
            clone_url=clone_url,
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
):
    """Upsert one GitHub pull request; start an analysis for its head commit."""

    pull_request = parse_pull_request(raw_pull_request)
    upserted, analysis = record_pull_request(
        repository_service=service,
        analysis_service=analysis_service,
        repository=repository,
        pull_request=pull_request,
        analyze=analyze,
    )
    if analysis is not None:
        _record_intent(http_request, analysis, pull_request, repository, principal)
    return upserted, analysis


def _record_intent(http_request, analysis, pull_request, repository, principal) -> None:
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


def _connected_repository(
    service: RepositoryApplicationService,
    principal: ApiPrincipal,
    repository_id: UUID,
):
    repository = _owned_repository(service, principal, repository_id)
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

    outcome = sync_open_pull_requests(
        repository_service=service,
        analysis_service=analysis_service,
        repository=repository,
        raw_pull_requests=raw_pull_requests,
        auto_analyze=auto_analyze,
        parse=parse_pull_request,
        on_analysis=lambda analysis, parsed: _record_intent(
            http_request, analysis, parsed, repository, principal
        ),
    )
    return success_response(
        outcome.synced,
        meta={
            "github": "synced",
            "installationId": access.installation_id,
            "analysisIds": outcome.analysis_ids,
            "skipped": outcome.skipped,
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


_PR_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/pull/(\d+)(?:/[\w-]+)*/?(?:[?#].*)?$"
)


@router.post("/import-pull-request", status_code=status.HTTP_202_ACCEPTED)
def import_public_pull_request(
    http_request: Request,
    request: ImportPullRequestRequest,
    service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
):
    """Connect a public GitHub repo from a PR link and queue an analysis of that PR.

    Works without the GitHub App: repo and PR are read from the public GitHub API
    (set GITHUB_TOKEN to raise the 60 requests/hour unauthenticated limit).
    """

    from radius_analysis.dto import StartAnalysisCommand
    from radius_repository.dto import UpsertPullRequestCommand
    from radius_shared.errors import ValidationError

    from radius_api.schemas.github_webhooks import (
        GitHubPullRequestPayload,
        GitHubRepositoryPayload,
    )

    match = _PR_URL.match(request.url.strip())
    if match is None:
        msg = "Paste a pull request link like https://github.com/OWNER/REPO/pull/123."
        raise ValidationError(msg)
    owner, name, number = match.group(1), match.group(2), int(match.group(3))

    repo_json = _github_get(f"/repos/{owner}/{name}")
    pr_json = _github_get(f"/repos/{owner}/{name}/pulls/{number}")
    repo_payload = GitHubRepositoryPayload.model_validate(repo_json)
    pr_payload = GitHubPullRequestPayload.model_validate(pr_json)
    if repo_payload.private:
        msg = "This repository is private. Private repositories need the GitHub App."
        raise ValidationError(msg)

    repository = service.get_by_github_repository_id(repo_payload.id)
    if repository is None:
        repository = service.connect_repository(
            ConnectRepositoryCommand(
                organization_id=principal.organization_id,
                github_repository_id=repo_payload.id,
                name=repo_payload.name,
                owner=repo_payload.owner.login,
                default_branch=repo_payload.default_branch,
                clone_url=validate_clone_url(
                    repo_payload.clone_url, policy=clone_policy(http_request)
                ),
                visibility=RepositoryVisibility.PUBLIC,
            )
        )
    else:
        ensure_same_organization(principal, repository.organization_id)

    if pr_payload.merged:
        pr_status = "merged"
    elif pr_payload.state == "closed":
        pr_status = "closed"
    else:
        pr_status = "open"
    pull_request = service.upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(str(repository.id)),
            github_pr_number=pr_payload.number,
            title=pr_payload.title,
            source_branch=pr_payload.head.ref,
            target_branch=pr_payload.base.ref,
            author=pr_payload.user.login,
            status=pr_status,
            opened_at=pr_payload.created_at,
            merged_at=pr_payload.merged_at,
        )
    )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(
            repository_id=UUID(str(repository.id)),
            pull_request_id=UUID(str(pull_request.id)),
            commit_sha=pr_payload.head.sha,
        )
    )
    return success_response(
        {
            "repositoryId": str(repository.id),
            "pullRequestId": str(pull_request.id),
            "analysisId": str(analysis.id),
            "repository": f"{repo_payload.owner.login}/{repo_payload.name}",
            "pullRequestNumber": pr_payload.number,
            "title": pr_payload.title,
            "commitSha": pr_payload.head.sha,
        }
    )


def _github_get(path: str) -> dict:
    import httpx
    from radius_shared.errors import ValidationError

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "radius"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(f"https://api.github.com{path}", headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        msg = f"Could not reach GitHub: {exc}"
        raise ValidationError(msg) from exc
    if response.status_code == 404:
        msg = "GitHub says this repository or pull request does not exist (or is private)."
        raise ValidationError(msg)
    if response.status_code == 403:
        msg = "GitHub rate limit reached. Set GITHUB_TOKEN on the API, or try again later."
        raise ValidationError(msg)
    if response.status_code != 200:
        msg = f"GitHub returned HTTP {response.status_code} for {path}."
        raise ValidationError(msg)
    return response.json()
