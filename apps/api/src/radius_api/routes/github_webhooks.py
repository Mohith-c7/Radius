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
from radius_shared.config import RuntimeEnvironment
from radius_shared.dto import success_response
from radius_shared.errors import AccessDeniedError, ValidationError

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
    existing = replay_or_validate(
        idempotency_store,
        _webhook_organization_id(request),
        delivery_id,
        scope,
        body_hash,
    )
    if existing is not None:
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
        )

    payload = json.loads(body)
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
        _webhook_organization_id(request),
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
    organization_id = _webhook_organization_id(request)
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
    secret = request.app.state.settings.github_webhook_secret
    is_production = (
        request.app.state.settings.environment == RuntimeEnvironment.PRODUCTION
    )
    if not secret:
        if is_production:
            msg = "GitHub webhook secret must be configured in production."
            raise AccessDeniedError(msg)
        return
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


def _webhook_organization_id(request: Request) -> UUID:
    organization_id = request.app.state.settings.github_default_organization_id
    if organization_id is None:
        msg = "GITHUB_DEFAULT_ORGANIZATION_ID is required for GitHub webhooks."
        raise ValidationError(msg)
    return organization_id


def _pull_request_status(payload: GitHubPullRequestPayload) -> str:
    if payload.merged:
        return "merged"
    if payload.state == "closed":
        return "closed"
    return "open"
