"""Admin API for managed API keys (PRD-12). Every route needs the admin scope.

A request that carries ``X-Radius-Session`` comes from a signed-in dashboard user through the
dashboard proxy, whose server-side key has every scope. For such a request the key's admin
scope is not enough: the session's user must also be an ADMIN of the request's organization
(403 otherwise), and the audit actor names that user. Requests without a session (automation
with its own key) keep the admin-scope rule alone.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from app.database import get_db as get_auth_db
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from radius_shared.database.enums import UserRole
from radius_shared.database.models import User as DomainUser
from radius_shared.dto import success_response
from radius_shared.errors import AccessDeniedError
from sqlalchemy import select
from sqlalchemy.orm import Session

from radius_api.api_keys import SCOPE_ADMIN, open_service
from radius_api.auth import ApiPrincipal, require_scope
from radius_api.confirmer import SESSION_HEADER
from radius_api.schemas.api_keys import (
    ApiKeyAuditView,
    ApiKeyCreated,
    ApiKeyCreateRequest,
    ApiKeyRotateRequest,
    ApiKeyView,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@dataclass(frozen=True, slots=True)
class AdminCaller:
    """Who manages keys: the organization and the audit actor (key, plus the dashboard user)."""

    organization_id: UUID
    actor: str


_NOT_ADMIN = "Managing API keys requires an organization admin."


def _session_admin(token: str, organization_id: UUID, auth_db: Session) -> str:
    """The user id of a session whose user is an ADMIN of ``organization_id``; 403 otherwise."""

    from app.routes_auth import _load_session

    try:
        user, _ = _load_session(token, auth_db)
    except HTTPException as exc:
        raise AccessDeniedError(_NOT_ADMIN) from exc
    member = auth_db.scalar(
        select(DomainUser).where(DomainUser.email == user.email.lower())
    )
    if (
        member is None
        or member.organization_id != organization_id
        or member.role != UserRole.ADMIN
    ):
        raise AccessDeniedError(_NOT_ADMIN)
    return str(user.id)


def _admin(
    principal: Annotated[ApiPrincipal, Depends(require_scope(SCOPE_ADMIN))],
    auth_db: Annotated[Session, Depends(get_auth_db)],
    session_token: Annotated[
        str | None,
        Header(
            alias=SESSION_HEADER,
            description="Signed session of the dashboard user acting (sent by the dashboard "
            "server, never by a browser). When present, that user must be an admin of the "
            "organization.",
        ),
    ] = None,
) -> AdminCaller:
    if session_token is None:
        return AdminCaller(principal.organization_id, principal.actor)
    user_id = _session_admin(session_token, principal.organization_id, auth_db)
    return AdminCaller(principal.organization_id, f"{principal.actor}/user={user_id}")


Admin = Annotated[AdminCaller, Depends(_admin)]


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
