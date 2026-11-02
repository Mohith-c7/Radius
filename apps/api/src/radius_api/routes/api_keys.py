"""Admin API for managed API keys (PRD-12). Every route needs the admin scope."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from radius_shared.dto import success_response

from radius_api.api_keys import SCOPE_ADMIN, open_service
from radius_api.auth import ApiPrincipal, require_scope
from radius_api.schemas.api_keys import (
    ApiKeyAuditView,
    ApiKeyCreated,
    ApiKeyCreateRequest,
    ApiKeyRotateRequest,
    ApiKeyView,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])
Admin = Annotated[ApiPrincipal, Depends(require_scope(SCOPE_ADMIN))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_api_key(body: ApiKeyCreateRequest, request: Request, principal: Admin):
    """Create a key for the caller's organization; the token is shown once."""

    with open_service(request) as service:
        key, token = service.create(
            principal.organization_id,
            name=body.name,
            scopes=body.scopes,
            actor=principal.actor,
            expires_at=body.expires_at,
        )
        return success_response(
            ApiKeyCreated(key=ApiKeyView.from_row(key), token=token)
        )


@router.get("")
def list_api_keys(request: Request, principal: Admin):
    """List the organization's keys (prefix only)."""

    with open_service(request) as service:
        rows = service.list(principal.organization_id)
        return success_response([ApiKeyView.from_row(r) for r in rows])


@router.get("/audit")
def list_api_key_audit(request: Request, principal: Admin):
    """List create, rotate and revoke events."""

    with open_service(request) as service:
        events = service.audit_events(principal.organization_id)
        return success_response(
            [
                ApiKeyAuditView(
                    id=e.id,
                    api_key_id=e.api_key_id,
                    action=e.action,
                    actor=e.actor,
                    detail=e.detail,
                    created_at=e.created_at,
                )
                for e in events
            ]
        )


@router.post("/{key_id}/rotate", status_code=status.HTTP_201_CREATED)
def rotate_api_key(
    key_id: UUID,
    body: ApiKeyRotateRequest,
    request: Request,
    principal: Admin,
):
    """Issue a replacement token; the old key expires after the overlap window."""

    with open_service(request) as service:
        new, token, old = service.rotate(
            principal.organization_id,
            key_id,
            actor=principal.actor,
            overlap_seconds=body.overlap_seconds,
        )
        return success_response(
            ApiKeyCreated(
                key=ApiKeyView.from_row(new),
                token=token,
                replaced=ApiKeyView.from_row(old),
            )
        )


@router.delete("/{key_id}")
def revoke_api_key(key_id: UUID, request: Request, principal: Admin):
    """Revoke a key immediately."""

    with open_service(request) as service:
        key = service.revoke(principal.organization_id, key_id, actor=principal.actor)
        return success_response(ApiKeyView.from_row(key))
