"""Request authentication and tenant context helpers."""

from dataclasses import dataclass
from hmac import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request
from radius_shared.config import RuntimeEnvironment
from radius_shared.errors import AccessDeniedError, ValidationError


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    """Authenticated API caller scoped to one organization."""

    organization_id: UUID


def _configured_api_keys(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    raw_keys = getattr(settings, "api_keys", "")
    configured: dict[str, str] = {}
    for item in raw_keys.split(","):
        if not item.strip():
            continue
        try:
            organization_id, api_key = item.split(":", 1)
        except ValueError as exc:
            msg = "API key configuration must use organization_id:key entries."
            raise ValidationError(msg) from exc
        configured[organization_id.strip()] = api_key.strip()
    return configured


def get_api_principal(
    request: Request,
    organization_id: Annotated[
        UUID | None,
        Header(alias="X-Radius-Organization-Id"),
    ] = None,
    api_key: Annotated[
        str | None,
        Header(alias="X-Radius-API-Key"),
    ] = None,
) -> ApiPrincipal:
    """Return the authenticated organization context for protected API routes."""

    if organization_id is None:
        msg = "X-Radius-Organization-Id header is required."
        raise AccessDeniedError(msg)

    configured_keys = _configured_api_keys(request)
    is_production = (
        request.app.state.settings.environment == RuntimeEnvironment.PRODUCTION
    )
    if is_production and not configured_keys:
        msg = "Radius API keys must be configured in production."
        raise AccessDeniedError(msg)

    if configured_keys:
        expected_key = configured_keys.get(str(organization_id))
        if expected_key is None or api_key is None or not compare_digest(
            api_key,
            expected_key,
        ):
            msg = "Invalid Radius API key for organization."
            raise AccessDeniedError(msg)

    return ApiPrincipal(organization_id=organization_id)


def ensure_same_organization(
    principal: ApiPrincipal,
    organization_id: UUID,
) -> None:
    """Raise when a request tries to cross tenant boundaries."""

    if principal.organization_id != organization_id:
        msg = "Resource does not belong to the authenticated organization."
        raise AccessDeniedError(msg)
