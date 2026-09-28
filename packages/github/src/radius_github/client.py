"""Small GitHub App REST client."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from pydantic import Field
from radius_shared.config import RadiusBaseSettings
from radius_shared.errors import AccessDeniedError, ValidationError


class GitHubAppSettings(RadiusBaseSettings):
    """Runtime settings required for GitHub App operations."""

    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_installation_id: int | None = Field(
        default=None,
        alias="GITHUB_INSTALLATION_ID",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        alias="GITHUB_API_BASE_URL",
    )
    github_api_version: str = Field(
        default="2026-03-10",
        alias="GITHUB_API_VERSION",
    )
    github_timeout_seconds: float = Field(
        default=10.0,
        alias="GITHUB_TIMEOUT_SECONDS",
    )

    @property
    def enabled(self) -> bool:
        """Return whether enough app credentials are configured."""

        return bool(self.github_app_id and self.github_app_private_key)


@dataclass(frozen=True, slots=True)
class InstallationToken:
    """GitHub installation access token response."""

    token: str
    expires_at: datetime | None = None


class GitHubAppClient:
    """Dependency-light REST client for GitHub App operations."""

    def __init__(
        self,
        settings: GitHubAppSettings,
        *,
        opener=None,
        clock=time.time,
    ) -> None:
        self._settings = settings
        self._opener = opener or urllib.request.urlopen
        self._clock = clock

    def create_installation_token(
        self,
        installation_id: int,
    ) -> InstallationToken:
        """Create an installation token for clone and publishing operations."""

        if not self._settings.enabled:
            msg = "GitHub App credentials are not configured."
            raise AccessDeniedError(msg)
        response = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._jwt(),
            body={},
        )
        if not isinstance(response, dict):
            msg = "GitHub returned an invalid installation token response."
            raise AccessDeniedError(msg)
        token = response.get("token")
        if not token:
            msg = "GitHub did not return an installation token."
            raise AccessDeniedError(msg)
        expires_at = response.get("expires_at")
        return InstallationToken(
            token=str(token),
            expires_at=(
                datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expires_at
                else None
            ),
        )

    def create_check_run(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        name: str,
        head_sha: str,
        title: str,
        summary: str,
        text: str,
        status: str = "completed",
        conclusion: str | None = None,
        details_url: str | None = None,
    ) -> dict[str, Any]:
        """Publish a GitHub Check Run."""

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/check-runs",
            token=token,
            body=_check_run_payload(
                name=name,
                head_sha=head_sha,
                status=status,
                conclusion=conclusion,
                title=title,
                summary=summary,
                text=text,
                details_url=details_url,
            ),
        )

    def update_check_run(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        check_run_id: int,
        name: str,
        head_sha: str,
        title: str,
        summary: str,
        text: str,
        status: str = "completed",
        conclusion: str | None = None,
        details_url: str | None = None,
    ) -> dict[str, Any]:
        """Update a GitHub Check Run."""

        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
            token=token,
            body=_check_run_payload(
                name=name,
                head_sha=head_sha,
                status=status,
                conclusion=conclusion,
                title=title,
                summary=summary,
                text=text,
                details_url=details_url,
            ),
        )

    def list_check_runs_for_ref(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        ref: str,
        check_name: str,
    ) -> list[dict[str, Any]]:
        """Return check runs matching one ref and check name."""

        query = urllib.parse.urlencode({"check_name": check_name, "per_page": 100})
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{ref}/check-runs?{query}",
            token=token,
        )
        if not isinstance(response, dict):
            return []
        check_runs = response.get("check_runs", [])
        return [item for item in check_runs if isinstance(item, dict)]

    def create_issue_comment(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Create a Pull Request comment through the Issues comments API."""

        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            token=token,
            body={"body": body},
        )

    def update_issue_comment(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
    ) -> dict[str, Any]:
        """Update an existing Pull Request comment."""

        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            token=token,
            body={"body": body},
        )

    def list_issue_comments(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        """Return recent comments for one issue or Pull Request."""

        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments?per_page=100",
            token=token,
        )
        return response if isinstance(response, list) else []

    def _jwt(self) -> str:
        issued_at = int(self._clock()) - 60
        expires_at = issued_at + 9 * 60
        private_key = self._settings.github_app_private_key.replace("\\n", "\n")
        return jwt.encode(
            {
                "iat": issued_at,
                "exp": expires_at,
                "iss": self._settings.github_app_id,
            },
            private_key,
            algorithm="RS256",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = urllib.parse.urljoin(
            self._settings.github_api_base_url.rstrip("/") + "/",
            path.lstrip("/"),
        )
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "radius-phase1",
                "X-GitHub-Api-Version": self._settings.github_api_version,
            },
        )
        try:
            with self._opener(
                request,
                timeout=self._settings.github_timeout_seconds,
            ) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8") or str(exc)
            raise AccessDeniedError(f"GitHub API request failed: {message}") from exc
        except urllib.error.URLError as exc:
            raise ValidationError(f"GitHub API request failed: {exc.reason}") from exc
        return json.loads(payload) if payload else {}


def _check_run_payload(
    *,
    name: str,
    head_sha: str,
    title: str,
    summary: str,
    text: str,
    status: str = "completed",
    conclusion: str | None = None,
    details_url: str | None = None,
) -> dict[str, Any]:
    if status == "in_progress":
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": "in_progress",
            "started_at": datetime.now(UTC).isoformat(),
            "output": {
                "title": title,
                "summary": summary,
                "text": text,
            },
        }
    else:
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "conclusion": conclusion or "neutral",
            "completed_at": datetime.now(UTC).isoformat(),
            "output": {
                "title": title,
                "summary": summary,
                "text": text,
            },
        }
    if details_url:
        payload["details_url"] = details_url
    return payload
