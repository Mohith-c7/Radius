"""Pull-based GitHub access: connect, sync and analyze without any webhook.

Everything here uses only the GitHub App credentials (App id + private key) and
outbound HTTPS calls from the API to GitHub. No public URL, tunnel or webhook
secret is involved. The flow is:

1. ``GET /repos/{owner}/{repo}/installation`` (App JWT) finds the installation
   that covers the repository, so the installation id does not have to be
   copied by hand or delivered by an ``installation`` webhook.
2. An installation token reads the repository and its pull requests.
3. The installation id is stored on the organization, which is where the
   worker looks it up to clone the repository and publish the Check Run and
   the pull request comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request
from radius_github import GitHubAppClient, GitHubHTTPError
from radius_github.pull_sync import pull_request_status  # noqa: F401  (re-export)
from radius_repository.domain.clone_url import GitUrlPolicy
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.errors import (
    AccessDeniedError,
    ConflictError,
    NotFoundError,
    RadiusError,
    ValidationError,
)

from radius_api.schemas.github_webhooks import GitHubPullRequestPayload

NOT_CONFIGURED = "GITHUB_APP_NOT_CONFIGURED"
NOT_INSTALLED = "GITHUB_APP_NOT_INSTALLED"
AUTH_FAILED = "GITHUB_APP_AUTH_FAILED"
REPO_NOT_ACCESSIBLE = "GITHUB_REPOSITORY_NOT_ACCESSIBLE"
GITHUB_ERROR = "GITHUB_API_ERROR"


@dataclass(frozen=True, slots=True)
class GitHubAccess:
    """A ready installation token for one repository."""

    client: GitHubAppClient
    installation_id: int
    token: str


def parse_owner_repo(value: str) -> tuple[str, str]:
    """Split ``owner/name`` (also accepts a github.com URL or a ``.git`` suffix)."""

    text = value.strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
    text = text.strip("/").removesuffix(".git")
    parts = text.split("/")
    if len(parts) != 2 or not all(parts):
        msg = "repository must look like owner/name."
        raise ValidationError(msg)
    owner, name = parts
    if owner in {".", ".."} or name in {".", ".."}:
        # Dot segments would be collapsed by URL joining and steer the request
        # to another GitHub API path.
        msg = "repository must look like owner/name."
        raise ValidationError(msg)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if not (set(owner) <= allowed and set(name) <= allowed):
        msg = "repository contains characters GitHub does not allow."
        raise ValidationError(msg)
    return owner, name


def clone_policy(request: Request) -> GitUrlPolicy:
    """Clone URL policy from the API settings (default: github.com over https)."""

    settings = getattr(request.app.state, "settings", None)
    policy = getattr(settings, "git_url_policy", None)
    return policy if isinstance(policy, GitUrlPolicy) else GitUrlPolicy()


def dev_single_tenant(request: Request) -> bool:
    """Whether ``RADIUS_GITHUB_DEV_SINGLE_TENANT`` lets an org adopt the App's installation."""

    settings = getattr(request.app.state, "settings", None)
    return bool(getattr(settings, "github_dev_single_tenant", False))


def require_configured(client: GitHubAppClient) -> None:
    """Fail with an actionable error when no App credentials are configured."""

    if not client.settings.enabled:
        raise ConflictError(
            "GitHub App credentials are not configured on the API. Set GITHUB_APP_ID "
            "and GITHUB_APP_PRIVATE_KEY (or GITHUB_APP_PRIVATE_KEY_PATH) for the API "
            "process, then restart it. See docs/operations/LIVE_GITHUB_DEMO.md.",
            code=NOT_CONFIGURED,
        )


def translate_github_error(exc: Exception, *, what: str) -> RadiusError:
    """Map a GitHub client failure to a Radius error with a next step."""

    if isinstance(exc, GitHubHTTPError):
        if exc.status == 401:
            return AccessDeniedError(
                f"GitHub rejected the App credentials while {what} (HTTP 401). Check "
                "GITHUB_APP_ID, that the private key belongs to this App, and that "
                "the machine clock is correct (JWTs are valid for 10 minutes).",
                code=AUTH_FAILED,
            )
        if exc.status == 404:
            return NotFoundError(
                f"GitHub returned 404 while {what}. The repository does not exist, "
                "or the App is not installed on it / lacks access.",
                code=REPO_NOT_ACCESSIBLE,
            )
        return AccessDeniedError(f"{exc} (while {what})", code=GITHUB_ERROR)
    if isinstance(exc, RadiusError):
        return exc
    return AccessDeniedError(
        f"GitHub request failed while {what}: {type(exc).__name__}", code=GITHUB_ERROR
    )


def _organization(request: Request, organization_id: UUID):
    session = getattr(request.state, "radius_db_session", None)
    if session is None:
        return None
    return session.get(db_models.Organization, organization_id)


def resolve_installation_id(
    request: Request,
    client: GitHubAppClient,
    *,
    organization_id: UUID,
    owner: str,
    repo: str,
    discover: bool = False,
) -> int:
    """Return the installation id for a repository, discovering it when unknown.

    Order matches the worker: ``GITHUB_INSTALLATION_ID`` first, then the id stored
    on the organization, then (pull-only deployments) discovery through GitHub.
    A discovered id is stored on the organization when it has none.
    """

    configured = client.settings.github_installation_id
    if configured:
        return int(configured)
    organization = _organization(request, organization_id)
    stored = organization.github_installation_id if organization else None
    if (
        stored
        and organization is not None
        and organization.github_installation_status
        == db_enums.GitHubInstallationStatus.DELETED.value
    ):
        stored = None  # a removed installation is no link at all
    if stored and not discover:
        return int(stored)
    if organization is not None and not stored and not dev_single_tenant(request):
        # A-03: the organization is not linked to any installation. GitHub
        # answers an installation lookup for ANY repository the (shared) App
        # covers, so adopting the result would let a caller attach another
        # customer's installation by naming their repository. Refuse before
        # asking GitHub, which also keeps this route from acting as an oracle
        # for which private repositories have the App installed.
        raise AccessDeniedError(
            "This organization is not linked to a GitHub App installation, and "
            "installations are not attached on the strength of a repository name. "
            "Have the installation linked to the organization first (see "
            "docs/security/INSTALLATION_BINDING.md); for a single-tenant "
            "development stack set RADIUS_GITHUB_DEV_SINGLE_TENANT=true.",
            code="GITHUB_INSTALLATION_NOT_LINKED",
        )
    try:
        found = client.get_repository_installation(owner, repo)
    except Exception as exc:  # noqa: BLE001 - translated to an actionable error
        if stored and not _is_not_found(exc):
            return int(stored)
        raise translate_github_error(
            exc, what=f"looking up the App installation of {owner}/{repo}"
        ) from exc
    discovered = found.get("id")
    if not discovered:
        raise NotFoundError(
            f"The GitHub App is not installed on {owner}/{repo}.", code=NOT_INSTALLED
        )
    discovered = int(discovered)
    if organization is None:
        return discovered
    if not stored:
        # Single-tenant development mode only (checked above). Even then an
        # installation that belongs to another organization is never taken.
        if _organization_with_installation(request, discovered, organization_id):
            raise ConflictError(
                f"{owner}/{repo} is covered by a GitHub installation that is linked to "
                "a different organization.",
                code="GITHUB_INSTALLATION_MISMATCH",
            )
        organization.github_installation_id = discovered
        organization.github_installation_status = (
            db_enums.GitHubInstallationStatus.ACTIVE.value
        )
    elif int(stored) != discovered:
        raise ConflictError(
            f"{owner}/{repo} is covered by GitHub installation {discovered}, but "
            f"this organization is linked to installation {stored}. One Radius "
            "organization uses one installation; install the App on this "
            "repository under the same account.",
            code="GITHUB_INSTALLATION_MISMATCH",
        )
    return discovered


def _organization_with_installation(
    request: Request, installation_id: int, except_organization_id: UUID
):
    session = getattr(request.state, "radius_db_session", None)
    if session is None:
        return None
    return (
        session.query(db_models.Organization)
        .filter(
            db_models.Organization.github_installation_id == installation_id,
            db_models.Organization.id != except_organization_id,
        )
        .first()
    )


def _is_not_found(exc: Exception) -> bool:
    return isinstance(exc, GitHubHTTPError) and exc.status == 404


def open_access(
    request: Request,
    client: GitHubAppClient,
    *,
    organization_id: UUID,
    owner: str,
    repo: str,
    discover: bool = False,
) -> GitHubAccess:
    """Resolve the installation and mint an installation token."""

    require_configured(client)
    installation_id = resolve_installation_id(
        request,
        client,
        organization_id=organization_id,
        owner=owner,
        repo=repo,
        discover=discover,
    )
    try:
        token = client.create_installation_token(installation_id).token
    except Exception as exc:  # noqa: BLE001
        raise translate_github_error(
            exc, what=f"creating an installation token for installation {installation_id}"
        ) from exc
    return GitHubAccess(client=client, installation_id=installation_id, token=token)


def parse_pull_request(raw: dict[str, Any], *, number: int | None = None):
    """Validate a REST pull request object; the error names what is missing."""

    try:
        return GitHubPullRequestPayload.model_validate(raw)
    except Exception as exc:
        label = f"#{number}" if number else str(raw.get("number", "?"))
        msg = f"GitHub returned an unexpected shape for pull request {label}."
        raise ValidationError(msg, code=GITHUB_ERROR) from exc
