"""Small GitHub App REST client."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from pydantic import Field, field_validator, model_validator
from radius_shared.config import RadiusBaseSettings
from radius_shared.errors import AccessDeniedError, ValidationError

from radius_github.rate_limit import (
    IDEMPOTENT_METHODS,
    TRANSIENT_STATUSES,
    GitHubRateLimitError,
    RateLimitInfo,
    RetryPolicy,
    backoff,
    classify_rate_limit,
    parse_rate_limit,
    short_message,
    wait_for_rate_limit,
)


class GitHubAppSettings(RadiusBaseSettings):
    """Runtime settings required for GitHub App operations."""

    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_app_private_key_path: str = Field(
        default="",
        alias="GITHUB_APP_PRIVATE_KEY_PATH",
        description=(
            "Path to the GitHub App private key (.pem). Used when "
            "`GITHUB_APP_PRIVATE_KEY` is empty, so the key never has to be pasted "
            "into an environment variable or committed."
        ),
    )
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

    @field_validator("github_installation_id", mode="before")
    @classmethod
    def _blank_installation_id(cls, value):
        if value is None or value in ("", 0, "0"):
            return None
        return value

    @model_validator(mode="after")
    def _load_private_key_file(self) -> GitHubAppSettings:
        if not self.github_app_private_key and self.github_app_private_key_path:
            self.github_app_private_key = read_private_key_file(
                self.github_app_private_key_path
            )
        return self

    @property
    def enabled(self) -> bool:
        """Return whether enough app credentials are configured."""

        return bool(self.github_app_id and self.github_app_private_key)


def read_private_key_file(path: str) -> str:
    """Read a PEM private key file; the error never contains key material."""

    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        msg = (
            f"GITHUB_APP_PRIVATE_KEY_PATH ({path}) cannot be read: "
            f"{type(exc).__name__}."
        )
        raise ValueError(msg) from exc


def normalize_private_key(raw: str) -> str:
    """Return a PEM string from an env-style value.

    Accepts a real multi-line PEM, a single line with literal backslash-n
    escapes (the usual ``.env`` form) and either of them wrapped in quotes.
    """

    key = raw.strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"'}:
        key = key[1:-1].strip()
    return key.replace("\\n", "\n")


class GitHubHTTPError(AccessDeniedError):
    """A GitHub API error response; ``status`` is the HTTP status code."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class InstallationToken:
    """GitHub installation access token response."""

    token: str
    expires_at: datetime | None = None
    #: Permissions GitHub granted the token (``{"checks": "write", ...}``).
    permissions: dict[str, str] | None = None
    repository_selection: str | None = None


class GitHubAppClient:
    """Dependency-light REST client for GitHub App operations."""

    def __init__(
        self,
        settings: GitHubAppSettings,
        *,
        opener=None,
        clock=time.time,
        retry_policy: RetryPolicy | None = None,
        sleep=time.sleep,
        rng=random.random,
    ) -> None:
        self._settings = settings
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._retry = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._rng = rng
        #: Rate-limit headers of the most recent response that carried them.
        self.last_rate_limit: RateLimitInfo | None = None
        #: ``Date`` header of the most recent response (clock-skew diagnostics).
        self.last_server_date: str | None = None

    @property
    def settings(self) -> GitHubAppSettings:
        """The settings this client signs and addresses requests with."""

        return self._settings

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
            permissions=(
                {str(k): str(v) for k, v in response["permissions"].items()}
                if isinstance(response.get("permissions"), dict)
                else None
            ),
            repository_selection=(
                str(response["repository_selection"])
                if response.get("repository_selection")
                else None
            ),
        )

    def get_app(self) -> dict[str, Any]:
        """Return the authenticated App (``GET /app``); proves the JWT is valid."""

        response = self._request("GET", "/app", token=self._jwt())
        return response if isinstance(response, dict) else {}

    def get_repository_installation(self, owner: str, repo: str) -> dict[str, Any]:
        """Return the App installation covering a repository (App JWT auth).

        Lets a pull-only deployment discover the installation id without any
        ``installation`` webhook.
        """

        response = self._request(
            "GET", f"/repos/{owner}/{repo}/installation", token=self._jwt()
        )
        return response if isinstance(response, dict) else {}

    def get_repository(self, *, token: str, owner: str, repo: str) -> dict[str, Any]:
        """Return repository metadata (id, default branch, clone URL, visibility)."""

        response = self._request("GET", f"/repos/{owner}/{repo}", token=token)
        return response if isinstance(response, dict) else {}

    def get_pull_request(
        self, *, token: str, owner: str, repo: str, number: int
    ) -> dict[str, Any]:
        """Return one pull request (head sha, title, body, author, state)."""

        response = self._request(
            "GET", f"/repos/{owner}/{repo}/pulls/{int(number)}", token=token
        )
        return response if isinstance(response, dict) else {}

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

    def list_pull_requests(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """Return pull requests for a repository from GitHub."""

        query = urllib.parse.urlencode({"state": state, "per_page": 100})
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls?{query}",
            token=token,
        )
        return response if isinstance(response, list) else []

    def _jwt(self) -> str:
        issued_at = int(self._clock()) - 60
        expires_at = issued_at + 9 * 60
        private_key = normalize_private_key(self._settings.github_app_private_key)
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
        attempt = 0
        waited = 0.0
        while True:
            attempt += 1
            try:
                with self._opener(
                    request,
                    timeout=self._settings.github_timeout_seconds,
                ) as response:
                    self._note_rate_limit(getattr(response, "headers", None))
                    payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as exc:
                body = _read_error_body(exc)
                self._note_rate_limit(exc.headers)
                delay = self._decide_http_retry(method, exc, body, attempt, waited)
                if delay is None:
                    raise self._http_error(
                        method, path, exc, body, attempt, waited
                    ) from exc
            except urllib.error.URLError as exc:
                delay = self._decide_network_retry(method, attempt, waited)
                if delay is None:
                    raise ValidationError(
                        f"GitHub API request failed: {exc.reason}"
                    ) from exc
            waited += delay
            self._sleep(delay)

    def _note_rate_limit(self, headers) -> None:
        self._note_date(headers)
        info = parse_rate_limit(headers)
        if info.remaining is not None or info.retry_after is not None:
            self.last_rate_limit = info

    def _note_date(self, headers) -> None:
        if headers is None:
            return
        try:
            value = headers.get("Date") or headers.get("date")
        except AttributeError:
            return
        if value:
            self.last_server_date = str(value)

    def _jittered(self, seconds: float) -> float:
        return seconds + seconds * self._retry.jitter_fraction * self._rng()

    def _fits(self, delay: float, attempt: int, waited: float) -> bool:
        return (
            attempt < self._retry.max_attempts
            and waited + delay <= self._retry.max_total_wait_seconds
        )

    def _decide_http_retry(
        self,
        method: str,
        exc: urllib.error.HTTPError,
        body: str,
        attempt: int,
        waited: float,
    ) -> float | None:
        """Seconds to sleep before retrying, or ``None`` to give up."""

        kind = classify_rate_limit(exc.code, exc.headers, body)
        if kind is not None:
            # Rejected before any work was done, so retrying is safe even for POST.
            info = parse_rate_limit(exc.headers)
            delay = self._jittered(
                wait_for_rate_limit(kind, info, self._clock(), attempt)
            )
            return delay if self._fits(delay, attempt, waited) else None
        if (
            exc.code in TRANSIENT_STATUSES
            and self._retry.retry_server_errors
            and method.upper() in IDEMPOTENT_METHODS
        ):
            info = parse_rate_limit(exc.headers)
            delay = self._jittered(
                max(backoff(self._retry, attempt), info.retry_after or 0.0)
            )
            return delay if self._fits(delay, attempt, waited) else None
        return None

    def _decide_network_retry(
        self, method: str, attempt: int, waited: float
    ) -> float | None:
        # A dropped connection or timeout may have happened after the server acted: only
        # idempotent methods are repeated.
        if (
            not self._retry.retry_server_errors
            or method.upper() not in IDEMPOTENT_METHODS
        ):
            return None
        delay = self._jittered(backoff(self._retry, attempt))
        return delay if self._fits(delay, attempt, waited) else None

    def _http_error(
        self,
        method: str,
        path: str,
        exc: urllib.error.HTTPError,
        body: str,
        attempt: int,
        waited: float,
    ) -> AccessDeniedError:
        kind = classify_rate_limit(exc.code, exc.headers, body)
        if kind is None:
            return GitHubHTTPError(
                f"GitHub API request failed (HTTP {exc.code}) on "
                f"{method} {path.split('?', 1)[0]}: {short_message(body) or exc}",
                status=exc.code,
            )
        info = parse_rate_limit(exc.headers)
        wanted = wait_for_rate_limit(kind, info, self._clock(), attempt)
        return GitHubRateLimitError(
            f"GitHub {kind} rate limit hit on {method} {path.split('?', 1)[0]} "
            f"(HTTP {exc.code}, {attempt} attempt(s), waited {waited:.1f}s, GitHub asks for "
            f"{wanted:.0f}s, retry budget {self._retry.max_total_wait_seconds:.0f}s): "
            f"{short_message(body)}",
            kind=kind,
            retry_after_seconds=wanted,
            attempts=attempt,
            waited_seconds=waited,
        )


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


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
