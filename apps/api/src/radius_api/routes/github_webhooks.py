"""GitHub webhook API routes."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import StartAnalysisCommand
from radius_repository.application import RepositoryApplicationService
from radius_repository.domain import RepositoryVisibility
from radius_repository.dto import (
    ConnectRepositoryCommand,
    UpsertBranchCommand,
    UpsertPullRequestCommand,
)
from radius_shared.database import models as db_models
from radius_shared.dto import success_response
from radius_shared.errors import AccessDeniedError, ValidationError
from radius_shared.logging import get_logger

from radius_api.dependencies import (
    get_analysis_service,
    get_idempotency_store,
    get_repository_service,
)
from radius_api.idempotency import IdempotencyStore, replay_or_validate
from radius_api.schemas.github_webhooks import (
    GitHubPullRequestPayload,
    GitHubRepositoryPayload,
    GitHubWebhookResult,
)

LOGGER = get_logger(__name__)

router = APIRouter(prefix="/webhooks/github", tags=["github-webhooks"])

_ANALYSIS_PR_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def handle_github_webhook(
    request: Request,
    repository_service: Annotated[
        RepositoryApplicationService,
        Depends(get_repository_service),
    ],
    analysis_service: Annotated[
        AnalysisApplicationService,
        Depends(get_analysis_service),
    ],
    idempotency_store: Annotated[
        IdempotencyStore,
        Depends(get_idempotency_store),
    ],
    event: Annotated[str, Header(alias="X-GitHub-Event")],
    delivery_id: Annotated[str, Header(alias="X-GitHub-Delivery")],
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
):
    """Handle signed GitHub webhook deliveries."""

    body = await request.body()
    _validate_signature(request, body, signature)
    body_hash = hashlib.sha256(body).hexdigest()
    scope = f"github_webhook:{event}"
    payload = json.loads(body)
    if event == "ping":
        # A ping carries no tenant context; acknowledge it without resolving one.
        result = GitHubWebhookResult(
            deliveryId=delivery_id,
            event=event,
            action=payload.get("action"),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=jsonable_encoder(success_response(result)),
        )
    org_id = _resolve_webhook_organization_id(request, payload, repository_service)
    # Repositories created while handling this delivery belong to this tenant.
    request.state.radius_webhook_org_id = org_id
    existing = replay_or_validate(
        idempotency_store,
        org_id,
        delivery_id,
        scope,
        body_hash,
    )
    if existing is not None:
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
        )

    _record_installation_id(request, payload, repository_service)
    result = _handle_payload(
        request,
        event,
        delivery_id,
        payload,
        repository_service,
        analysis_service,
    )
    response = success_response(result)
    response_body = jsonable_encoder(response)
    idempotency_store.save(
        org_id,
        delivery_id,
        scope,
        body_hash,
        status.HTTP_202_ACCEPTED,
        response_body,
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=response_body)


def _handle_payload(
    request: Request,
    event: str,
    delivery_id: str,
    payload: dict[str, Any],
    repository_service: RepositoryApplicationService,
    analysis_service: AnalysisApplicationService,
) -> GitHubWebhookResult:
    action = payload.get("action")
    if event == "ping":
        return GitHubWebhookResult(deliveryId=delivery_id, event=event, action=action)
    if event in ("installation", "installation_repositories"):
        return _handle_installation_sync(
            request,
            event,
            delivery_id,
            payload,
            repository_service,
        )
    if event == "push":
        return _handle_push(
            request,
            delivery_id,
            payload,
            repository_service,
        )
    if event == "pull_request":
        return _handle_pull_request(
            request,
            delivery_id,
            payload,
            repository_service,
            analysis_service,
        )
    return GitHubWebhookResult(
        deliveryId=delivery_id,
        event=event,
        action=action,
        ignored=True,
    )


def _handle_installation_sync(
    request: Request,
    event: str,
    delivery_id: str,
    payload: dict[str, Any],
    repository_service: RepositoryApplicationService,
) -> GitHubWebhookResult:
    action = payload.get("action")
    repos = []
    if event == "installation" and action == "created":
        repos = payload.get("repositories", [])
    elif event == "installation_repositories" and action == "added":
        repos = payload.get("repositories_added", [])
        
    for repo in repos:
        full_name = repo.get("full_name", "")
        owner_login = full_name.split("/")[0] if "/" in full_name else ""
        repo_payload = {
            "id": repo.get("id"),
            "name": repo.get("name", ""),
            "full_name": full_name,
            "owner": {"login": owner_login},
            "private": repo.get("private", False),
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "clone_url": f"https://github.com/{full_name}.git",
        }
        _connect_repository(
            request,
            GitHubRepositoryPayload.model_validate(repo_payload),
            repository_service,
        )
    return GitHubWebhookResult(deliveryId=delivery_id, event=event, action=action)


def _handle_push(
    request: Request,
    delivery_id: str,
    payload: dict[str, Any],
    repository_service: RepositoryApplicationService,
) -> GitHubWebhookResult:
    repository = _connect_repository(
        request,
        GitHubRepositoryPayload.model_validate(payload["repository"]),
        repository_service,
    )
    ref = str(payload.get("ref", ""))
    branch_name = ref.removeprefix("refs/heads/") or repository.default_branch
    repository_service.upsert_branch(
        UpsertBranchCommand(
            repository_id=UUID(str(repository.id)),
            name=branch_name,
            latest_commit_sha=payload.get("after"),
        )
    )
    return GitHubWebhookResult(
        deliveryId=delivery_id,
        event="push",
        repositoryId=str(repository.id),
    )


def _handle_pull_request(
    request: Request,
    delivery_id: str,
    payload: dict[str, Any],
    repository_service: RepositoryApplicationService,
    analysis_service: AnalysisApplicationService,
) -> GitHubWebhookResult:
    action = payload.get("action")
    repository = _connect_repository(
        request,
        GitHubRepositoryPayload.model_validate(payload["repository"]),
        repository_service,
    )
    pull_request_payload = GitHubPullRequestPayload.model_validate(
        payload["pull_request"]
    )
    pull_request = repository_service.upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(str(repository.id)),
            github_pr_number=pull_request_payload.number,
            title=pull_request_payload.title,
            source_branch=pull_request_payload.head.ref,
            target_branch=pull_request_payload.base.ref,
            author=pull_request_payload.user.login,
            status=_pull_request_status(pull_request_payload),
            opened_at=pull_request_payload.created_at,
            merged_at=pull_request_payload.merged_at,
        )
    )
    if action not in _ANALYSIS_PR_ACTIONS or pull_request_payload.draft:
        return GitHubWebhookResult(
            deliveryId=delivery_id,
            event="pull_request",
            action=action,
            ignored=True,
            repositoryId=str(repository.id),
            pullRequestId=str(pull_request.id),
        )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(
            repository_id=UUID(str(repository.id)),
            pull_request_id=UUID(str(pull_request.id)),
            commit_sha=pull_request_payload.head.sha,
        )
    )
    return GitHubWebhookResult(
        deliveryId=delivery_id,
        event="pull_request",
        action=action,
        repositoryId=str(repository.id),
        pullRequestId=str(pull_request.id),
        analysisId=str(analysis.id),
    )


def _connect_repository(
    request: Request,
    payload: GitHubRepositoryPayload,
    repository_service: RepositoryApplicationService,
):
    existing = repository_service.get_by_github_repository_id(payload.id)
    if existing is not None:
        return existing

    organization_id = getattr(request.state, "radius_webhook_org_id", None)
    if organization_id is None:
        organization_id = _resolve_webhook_organization_id(
            request,
            {"repository": {"id": payload.id}},
            repository_service,
        )
    repository = repository_service.connect_repository(
        ConnectRepositoryCommand(
            organization_id=organization_id,
            github_repository_id=payload.id,
            name=payload.name,
            owner=payload.owner.login,
            default_branch=payload.default_branch,
            clone_url=payload.clone_url,
            visibility=(
                RepositoryVisibility.PRIVATE
                if payload.private
                else RepositoryVisibility.PUBLIC
            ),
        )
    )
    if repository.organization_id != organization_id:
        msg = "GitHub repository is already connected to another organization."
        raise AccessDeniedError(msg)
    return repository


def _validate_signature(
    request: Request,
    body: bytes,
    signature: str | None,
) -> None:
    settings = request.app.state.settings
    secret = settings.github_webhook_secret
    if not secret:
        # Fail closed: an unsigned endpoint lets anyone enqueue analyses and
        # register repositories. Only an explicit dev/test opt-in skips this.
        if getattr(settings, "insecure_dev_mode", False):
            return
        msg = (
            "GitHub webhook secret is not configured. Set GITHUB_WEBHOOK_SECRET, "
            "or RADIUS_ALLOW_INSECURE_DEV=true for local development only."
        )
        raise AccessDeniedError(msg)
    if signature is None:
        msg = "Missing GitHub webhook signature."
        raise AccessDeniedError(msg)
    expected = "sha256=" + hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        msg = "Invalid GitHub webhook signature."
        raise AccessDeniedError(msg)


def _resolve_webhook_organization_id(
    request: Request,
    payload: dict[str, Any] | None = None,
    repository_service: RepositoryApplicationService | None = None,
) -> UUID:
    """Resolve the tenant for a delivery.

    Order: the organization that already owns the repository, then the
    organization linked to the delivery's GitHub App installation. The
    configured default organization is used only in explicit single-tenant
    mode; otherwise an unknown installation is rejected so one customer's
    repositories are never filed under another organization.
    """
    if payload and repository_service:
        repo_data = payload.get("repository")
        if isinstance(repo_data, dict) and repo_data.get("id"):
            existing = repository_service.get_by_github_repository_id(int(repo_data["id"]))
            if existing is not None:
                return existing.organization_id

    if payload:
        installation = payload.get("installation")
        if isinstance(installation, dict) and installation.get("id"):
            session = getattr(request.state, "radius_db_session", None)
            if session is not None:
                org = (
                    session.query(db_models.Organization)
                    .filter_by(github_installation_id=int(installation["id"]))
                    .first()
                )
                if org is not None:
                    return org.id

    settings = request.app.state.settings
    if getattr(settings, "github_single_tenant", False):
        organization_id = settings.github_default_organization_id
        if organization_id is not None:
            return organization_id
        msg = "GITHUB_DEFAULT_ORGANIZATION_ID is required when GITHUB_SINGLE_TENANT is enabled."
        raise ValidationError(msg)

    msg = "Unknown GitHub installation; connect it to an organization first."
    raise AccessDeniedError(msg)


def _webhook_organization_id(request: Request) -> UUID:
    return _resolve_webhook_organization_id(request)


def _pull_request_status(payload: GitHubPullRequestPayload) -> str:
    if payload.merged:
        return "merged"
    if payload.state == "closed":
        return "closed"
    return "open"


def _record_installation_id(
    request: Request,
    payload: dict[str, Any],
    repository_service: RepositoryApplicationService | None = None,
) -> None:
    installation = payload.get("installation")
    if not isinstance(installation, dict) or installation.get("id") is None:
        return
    session = getattr(request.state, "radius_db_session", None)
    if session is None:
        return
    try:
        org_id = _resolve_webhook_organization_id(
            request,
            payload=payload,
            repository_service=repository_service,
        )
    except (ValidationError, AccessDeniedError):
        return
    organization = session.get(db_models.Organization, org_id)
    if organization is None:
        return
    installation_id = int(installation["id"])
    if organization.github_installation_id is None:
        organization.github_installation_id = installation_id
    elif organization.github_installation_id != installation_id:
        # Never silently re-point an organization at another installation:
        # its tokens would then be used for this organization's repositories.
        LOGGER.warning(
            "Ignoring GitHub installation %s for organization %s already linked to %s",
            installation_id,
            org_id,
            organization.github_installation_id,
        )
