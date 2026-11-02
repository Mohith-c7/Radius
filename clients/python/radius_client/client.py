"""Thin synchronous client for the stable Radius HTTP API (``/api/v1``)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlencode

from radius_client.errors import (
    ApiError,
    TransportError,
    error_from_response,
)
from radius_client.models import (
    Analysis,
    ConfidenceReport,
    CriterionResult,
    IntentSnapshot,
    UploadResult,
    Versioned,
)
from radius_client.transport import Transport, TransportResponse, UrllibTransport

__all__ = ["RadiusClient", "parse_retry_after"]

_RETRYABLE_READ_STATUSES = frozenset({502, 503, 504})


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds."""

    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class RadiusClient:
    """Client bound to one organization.

    Args:
        base_url: Server root, for example ``https://radius.example.com`` (no ``/api/v1``).
        organization_id: Sent as ``X-Radius-Organization-Id``.
        api_key: Sent as ``X-Radius-API-Key`` (omit only against insecure dev servers).
        transport: Replace the HTTP layer (tests, proxies). Defaults to ``urllib``.
        max_retries: Extra attempts after a 429 (any method) or a transient failure
            of a GET (502/503/504 or a connection error).
        max_retry_after: Longest ``Retry-After`` the client is willing to sleep for;
            a longer request raises ``RateLimitedError`` immediately.
        sleep: Injected for tests.
    """

    API_PREFIX = "/api/v1"

    def __init__(
        self,
        base_url: str,
        organization_id: str,
        api_key: str | None = None,
        *,
        transport: Transport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_retry_after: float = 60.0,
        backoff_base: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = "radius-client-python/0.1.0",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._organization_id = str(organization_id)
        self._api_key = api_key
        self._transport = transport or UrllibTransport()
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._max_retry_after = max_retry_after
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._user_agent = user_agent

    def __repr__(self) -> str:  # never print the API key
        return f"RadiusClient(base_url={self._base!r}, organization_id={self._organization_id!r})"

    # -- analyses -------------------------------------------------------------

    def list_analyses(
        self,
        *,
        repository_id: str | None = None,
        pull_request_id: str | None = None,
        status: str | None = None,
    ) -> list[Analysis]:
        """List analyses of the organization, optionally filtered."""

        data, _ = self._call(
            "GET",
            "/analyses",
            params={
                "repositoryId": repository_id,
                "pullRequestId": pull_request_id,
                "status": status,
            },
        )
        return data

    def get_analysis(self, analysis_id: str) -> Analysis:
        """Return one analysis (``NotFoundError`` if unknown or foreign)."""

        data, _ = self._call("GET", f"/analyses/{_seg(analysis_id)}")
        return data

    def lookup_analysis(
        self,
        *,
        pull_request: int,
        commit_sha: str,
        repository: str | None = None,
        repository_id: str | None = None,
    ) -> Analysis:
        """Resolve the newest analysis of ``(repository, PR number, head sha)``."""

        data, _ = self._call(
            "GET",
            "/analyses/lookup",
            params={
                "pullRequest": pull_request,
                "commitSha": commit_sha,
                "repository": repository,
                "repositoryId": repository_id,
            },
        )
        return data

    # -- confidence -----------------------------------------------------------

    def get_confidence(self, analysis_id: str) -> ConfidenceReport:
        """Return the confidence report (404 until the analysis has produced one)."""

        data, _ = self._call("GET", f"/analyses/{_seg(analysis_id)}/confidence")
        return data

    # -- tests ----------------------------------------------------------------

    def upload_test_results(
        self,
        analysis_id: str,
        report: bytes | str,
        *,
        commit_sha: str,
        content_type: str = "application/xml",
    ) -> UploadResult:
        """Upload one CI test report (JUnit XML or Radius JSON) for ``commit_sha``.

        Raises ``ConflictError`` while the analysis is not completed, when it was
        superseded by a newer head commit, or when ``commit_sha`` differs from the
        analysed one.
        """

        body = report.encode("utf-8") if isinstance(report, str) else report
        data, _ = self._call(
            "POST",
            f"/analyses/{_seg(analysis_id)}/tests/results",
            params={"commit_sha": commit_sha},
            raw_body=body,
            content_type=content_type,
        )
        return data

    # -- intent ---------------------------------------------------------------

    def get_intent(self, analysis_id: str) -> Versioned[IntentSnapshot]:
        """Return the latest intent snapshot with its ETag."""

        data, headers = self._call("GET", f"/analyses/{_seg(analysis_id)}/intent")
        return Versioned(data, headers.get("etag") or data.get("etag"))

    def update_criterion(
        self,
        analysis_id: str,
        criterion_id: str,
        action: str,
        *,
        text: str | None = None,
        reason: str | None = None,
        if_match: str | None = None,
        actor: str | None = None,
    ) -> Versioned[CriterionResult]:
        """Apply ``confirm``, ``reject``, ``edit`` or ``reopen`` to a criterion.

        Pass the ETag of your last read as ``if_match``; a concurrent change raises
        ``StaleEtagError`` (re-read with ``get_intent`` and decide again).
        """

        payload: dict[str, Any] = {"action": action}
        if text is not None:
            payload["text"] = text
        if reason is not None:
            payload["reason"] = reason
        data, headers = self._call(
            "PATCH",
            f"/analyses/{_seg(analysis_id)}/intent/criteria/{_seg(criterion_id)}",
            json_body=payload,
            extra_headers={"If-Match": if_match, "X-Radius-Actor": actor},
        )
        return Versioned(data, headers.get("etag") or data.get("etag"))

    def confirm_criterion(
        self,
        analysis_id: str,
        criterion_id: str,
        *,
        if_match: str | Versioned[Any] | None = None,
        reason: str | None = None,
        actor: str | None = None,
    ) -> Versioned[CriterionResult]:
        """Confirm a criterion. ``if_match`` may be the ``Versioned`` from a read."""

        return self.update_criterion(
            analysis_id,
            criterion_id,
            "confirm",
            reason=reason,
            if_match=if_match.etag if isinstance(if_match, Versioned) else if_match,
            actor=actor,
        )

    # -- plumbing -------------------------------------------------------------

    def _headers(self, extra: Mapping[str, str | None] | None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self._user_agent,
            "X-Radius-Organization-Id": self._organization_id,
        }
        if self._api_key:
            headers["X-Radius-API-Key"] = self._api_key
        headers.update({k: v for k, v in (extra or {}).items() if v is not None})
        return headers

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        raw_body: bytes | None = None,
        content_type: str | None = None,
        extra_headers: Mapping[str, str | None] | None = None,
    ) -> tuple[Any, Mapping[str, str]]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self._base}{self.API_PREFIX}{path}" + (f"?{query}" if query else "")
        headers = self._headers(extra_headers)
        body = raw_body
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            content_type = "application/json"
        if content_type and body is not None:
            headers["Content-Type"] = content_type

        response = self._send(method, url, headers, body)
        parsed = _parse_json(response.body)
        if 200 <= response.status < 300:
            if not isinstance(parsed, dict) or "data" not in parsed:
                msg = "Response is not a Radius success envelope."
                raise ApiError(
                    response.status, "INVALID_RESPONSE", msg,
                    headers=response.headers, body=parsed,
                )
            return parsed["data"], response.headers
        raise error_from_response(response.status, response.headers, parsed)

    def _send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> TransportResponse:
        is_read = method == "GET"
        attempt = 0
        while True:
            try:
                response = self._transport.request(
                    method, url, headers, body, self._timeout
                )
            except TransportError:
                if not is_read or attempt >= self._max_retries:
                    raise
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            delay = self._retry_delay(response, attempt, is_read=is_read)
            if delay is None or attempt >= self._max_retries:
                return response
            self._sleep(delay)
            attempt += 1

    def _retry_delay(
        self, response: TransportResponse, attempt: int, *, is_read: bool
    ) -> float | None:
        if response.status == 429:
            asked = parse_retry_after(response.headers.get("retry-after"))
            delay = self._backoff(attempt) if asked is None else asked
            # Do not park the caller for longer than they allowed: surface the 429.
            return None if delay > self._max_retry_after else delay
        if is_read and response.status in _RETRYABLE_READ_STATUSES:
            return self._backoff(attempt)
        return None

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_base * (2**attempt), self._max_retry_after)


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _seg(value: object) -> str:
    """Percent-encode one path segment."""

    return quote(str(value), safe="")

