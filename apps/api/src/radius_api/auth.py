"""Request authentication and tenant context helpers."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from hmac import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from radius_shared.errors import AccessDeniedError, ValidationError

from radius_api.api_keys import (
    ALL_SCOPES,
    SCOPE_ADMIN,
    SCOPE_CI_UPLOAD,
    SCOPE_READ,
    SCOPE_WRITE,
    effective_scopes,
    open_service,
)
from radius_api.token_fingerprint import looks_like_managed_token

_INVALID_KEY = "Invalid Radius API key for organization."
_CI_UPLOAD_PATH = re.compile(r"^/api/v1/(analyses/[^/]+/tests/results|coverage)/?$")
_ADMIN_PATH = re.compile(r"^/api/v1/api-keys(/|$)")


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    """Authenticated API caller scoped to one organization."""

    organization_id: UUID
    #: Effective scopes; the default (legacy env keys, insecure dev) is full access.
    scopes: frozenset[str] = ALL_SCOPES
    #: ``managed`` | ``legacy`` | ``dev``
    source: str = "legacy"
    key_id: UUID | None = None
    key_prefix: str | None = None

    @property
    def actor(self) -> str:
        """Stable, secret-free label for audit entries."""

        if self.key_prefix:
            return f"key:rdk_{self.key_prefix}"
        return {"legacy": "legacy-env-key", "dev": "insecure-dev"}.get(
            self.source, self.source
        )


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


def required_scope(method: str, path: str) -> str:
    """Default scope mapping for a request (the GitHub webhook has its own auth).

    ``/api/v1/api-keys`` needs admin; test-result and coverage upload need
    ci-upload; other reads need read; every other mutation needs write.
    """

    if _ADMIN_PATH.match(path):
        return SCOPE_ADMIN
    if method == "POST" and _CI_UPLOAD_PATH.match(path):
        return SCOPE_CI_UPLOAD
    if method in {"GET", "HEAD", "OPTIONS"}:
        return SCOPE_READ
    return SCOPE_WRITE


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

    principal = _authenticate(request, organization_id, api_key)
    needed = required_scope(request.method, request.url.path)
    if needed not in effective_scopes(principal.scopes):
        msg = f"API key lacks the required '{needed}' scope."
        raise AccessDeniedError(msg)
    return principal


def _authenticate(
    request: Request, organization_id: UUID, api_key: str | None
) -> ApiPrincipal:
    if api_key is not None and looks_like_managed_token(api_key):
        with open_service(request) as service:
            key = service.authenticate(organization_id, api_key)
            if key is None:
                raise AccessDeniedError(_INVALID_KEY)
            return ApiPrincipal(
                organization_id=organization_id,
                scopes=frozenset(key.scopes),
                source="managed",
                key_id=key.id,
                key_prefix=key.prefix,
            )

    configured_keys = _configured_api_keys(request)
    if configured_keys:
        expected_key = configured_keys.get(str(organization_id))
        if expected_key is None or api_key is None or not compare_digest(
            api_key.encode(),
            expected_key.encode(),
        ):
            raise AccessDeniedError(_INVALID_KEY)
        return ApiPrincipal(organization_id=organization_id, source="legacy")

    if not _insecure_dev_mode(request):
        # Fail closed: without API keys every caller could claim any
        # organization. Only an explicit dev/test opt-in tolerates that.
        msg = (
            "Radius API keys are not configured. Create a managed key "
            "(RADIUS_API_KEY_PEPPER), set the deprecated API_KEYS, or set "
            "RADIUS_ALLOW_INSECURE_DEV=true for local development only."
        )
        raise AccessDeniedError(msg)
    return ApiPrincipal(organization_id=organization_id, source="dev")


def require_scope(scope: str) -> Callable[..., ApiPrincipal]:
    """Dependency factory: explicit per-route scope check (defense in depth)."""

    def dependency(
        principal: Annotated[ApiPrincipal, Depends(get_api_principal)],
    ) -> ApiPrincipal:
        if scope not in effective_scopes(principal.scopes):
            msg = f"API key lacks the required '{scope}' scope."
            raise AccessDeniedError(msg)
        return principal

    return dependency


def _insecure_dev_mode(request: Request) -> bool:
    settings = request.app.state.settings
    return bool(getattr(settings, "insecure_dev_mode", False))


def ensure_same_organization(
    principal: ApiPrincipal,
    organization_id: UUID,
) -> None:
    """Raise when a request tries to cross tenant boundaries."""

    if principal.organization_id != organization_id:
        msg = "Resource does not belong to the authenticated organization."
        raise AccessDeniedError(msg)
