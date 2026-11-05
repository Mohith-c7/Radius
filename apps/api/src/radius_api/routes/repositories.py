"""Repository API routes."""

import os
import re
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
    ImportPullRequestRequest,
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


_PR_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/pull/(\d+)(?:/[\w-]+)*/?(?:[?#].*)?$"
)


@router.post("/import-pull-request", status_code=status.HTTP_202_ACCEPTED)
def import_public_pull_request(
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
                clone_url=repo_payload.clone_url,
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
