"""Read-only GitHub REST access for intent ingestion (IN-02).

A small, dependency-free GET client with the properties ingestion needs and
:class:`radius_github.client.GitHubAppClient` (a publisher client that turns
every HTTP error into an exception) does not give:

* the HTTP **status and headers** are visible, so 403 (permission) can be told
  apart from 403 (rate limit), and 404/410 from outages;
* a per-analysis **call budget and deadline** (:class:`CallBudget`);
* **conditional requests** (``If-None-Match``) through a bounded in-process
  :class:`EtagCache`; a 304 does not count against GitHub's primary rate limit;
* the transport is an injectable callable, so tests run a stateful fake GitHub
  (``radius_github.fake_api``) without sockets.

Failures never raise: each call returns an :class:`ApiResult` whose ``kind`` is

``ok``           200 (or 304 answered from the cache);
``absent``       the resource is not there for this App: 403 without a rate-limit
                 signal (permission missing), 404, 410, 451, 422;
``unavailable``  a transient or systemic problem: rate limit, 401, 5xx, timeouts,
                 redirects, bad JSON, exhausted budget or deadline. Ingestion keeps
                 whatever it stored earlier for such a source.

Real-GitHub-only behavior is limited to the header and status conventions
documented at https://docs.github.com/rest (rate limits, ETags, error codes);
see ``docs/github-app-validation/RUNBOOK.md`` for what the live run must confirm.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

#: Hard cap on a response body read from the wire.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REDIRECTS = frozenset({301, 302, 303, 307, 308})

ResultKind = Literal["ok", "absent", "unavailable"]


@dataclass(frozen=True)
class HttpResponse:
    """A response as the transport saw it. Header names are lower-case."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


class TransportError(Exception):
    """The request did not produce an HTTP response (DNS, TLS, timeout...)."""

    def __init__(self, reason: str = "network_error") -> None:
        super().__init__(reason)
        self.reason = reason


class HttpTransport(Protocol):
    """Perform one HTTP request. Must not follow redirects or raise on 4xx/5xx."""

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Return the response or raise :class:`TransportError`."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        return None


class UrllibTransport:
    """Default transport on ``urllib`` (no redirects, bounded body)."""

    def __init__(self, max_bytes: int = MAX_RESPONSE_BYTES) -> None:
        self._max_bytes = max_bytes
        self._opener = urllib.request.build_opener(_NoRedirect)

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Send the request; HTTP errors are returned, network errors raised."""
        request = urllib.request.Request(url, method=method, headers=dict(headers))
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(self._max_bytes + 1)
                return HttpResponse(
                    response.status, _lower(response.headers.items()), body
                )
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(self._max_bytes + 1)
            except OSError:  # pragma: no cover - body already gone
                body = b""
            return HttpResponse(exc.code, _lower(exc.headers.items()), body)
        except TimeoutError as exc:
            raise TransportError("timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TransportError("timeout") from exc
            raise TransportError("network_error") from exc
        except OSError as exc:  # pragma: no cover - socket-level failures
            raise TransportError("network_error") from exc


def _lower(items: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in items}


@dataclass
class CallBudget:
    """At most ``max_calls`` requests and ``deadline_seconds`` of wall time.

    ``tripped`` is set to a reason once a rate limit or an authentication failure
    shows that more calls would be pointless; every later call is refused with
    that reason without touching the network.
    """

    max_calls: int = 15
    deadline_seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    used: int = 0
    tripped: str | None = None
    _started: float | None = None

    def __post_init__(self) -> None:
        self._started = self.clock()

    def remaining_seconds(self) -> float:
        """Seconds left before the deadline."""
        return self.deadline_seconds - (self.clock() - (self._started or 0.0))

    def acquire(self) -> str | None:
        """Reserve one call; return a refusal reason or ``None``."""
        if self.tripped:
            return self.tripped
        if self.used >= self.max_calls:
            return "budget_exhausted"
        if self.remaining_seconds() <= 0:
            return "deadline_exceeded"
        self.used += 1
        return None

    @property
    def exhausted(self) -> bool:
        """True once no further call can be made."""
        return bool(self.tripped) or self.used >= self.max_calls


class EtagCache:
    """Bounded LRU of ``(scope, url) -> (etag, parsed JSON)``.

    ``scope`` separates installations: two installations may see different data
    at the same URL. Process-local by design; across worker restarts the first
    request is unconditional.
    """

    def __init__(self, max_entries: int = 256) -> None:
        self._max = max(1, max_entries)
        self._items: OrderedDict[tuple[str, str], tuple[str, Any]] = OrderedDict()

    def get(self, scope: str, url: str) -> tuple[str, Any] | None:
        """Return the cached ``(etag, data)`` and mark it recently used."""
        key = (scope, url)
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
        return item

    def put(self, scope: str, url: str, etag: str, data: Any) -> None:
        """Remember a 200 response."""
        key = (scope, url)
        self._items[key] = (etag, data)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class ApiResult:
    """Outcome of one GET."""

    kind: ResultKind
    status: int | None = None
    data: Any = None
    reason: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        """True when ``data`` is usable."""
        return self.kind == "ok"


class GitHubRestReader:
    """GET JSON from the GitHub REST API within a :class:`CallBudget`."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        timeout_seconds: float = 10.0,
        transport: HttpTransport | None = None,
        cache: EtagCache | None = None,
        user_agent: str = "radius-intent-ingestion",
    ) -> None:
        self._base = base_url.rstrip("/") + "/"
        self._version = api_version
        self._timeout = timeout_seconds
        self._transport: HttpTransport = transport or UrllibTransport()
        self._cache = cache
        self._agent = user_agent

    def get_json(
        self,
        path: str,
        *,
        token: str,
        budget: CallBudget,
        scope: str = "",
        params: Mapping[str, str | int] | None = None,
    ) -> ApiResult:
        """GET ``path`` (relative to the API root) and classify the outcome."""
        refusal = budget.acquire()
        if refusal is not None:
            return ApiResult("unavailable", reason=refusal)
        url = urllib.parse.urljoin(self._base, path.lstrip("/"))
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": self._agent,
            "X-GitHub-Api-Version": self._version,
        }
        cached = self._cache.get(scope, url) if self._cache is not None else None
        if cached is not None:
            headers["If-None-Match"] = cached[0]
        timeout = max(0.1, min(self._timeout, budget.remaining_seconds()))
        try:
            response = self._transport("GET", url, headers, timeout)
        except TransportError as exc:
            return ApiResult("unavailable", reason=exc.reason)
        except Exception:  # a transport bug must not break ingestion
            return ApiResult("unavailable", reason="network_error")
        return self._classify(response, cached, scope, url, budget)

    def _classify(
        self,
        response: HttpResponse,
        cached: tuple[str, Any] | None,
        scope: str,
        url: str,
        budget: CallBudget,
    ) -> ApiResult:
        status = response.status
        if status == 304:
            if cached is None:
                return ApiResult("unavailable", status, reason="invalid_response")
            return ApiResult("ok", status, cached[1], from_cache=True)
        if status == 200:
            if len(response.body) > MAX_RESPONSE_BYTES:
                return ApiResult("unavailable", status, reason="response_too_large")
            try:
                data = json.loads(response.body.decode("utf-8")) if response.body else None
            except (UnicodeDecodeError, ValueError):
                return ApiResult("unavailable", status, reason="invalid_response")
            etag = response.headers.get("etag")
            if etag and self._cache is not None and data is not None:
                self._cache.put(scope, url, etag, data)
            return ApiResult("ok", status, data)
        if status in (403, 429) and _is_rate_limited(response):
            budget.tripped = "rate_limited"
            return ApiResult("unavailable", status, reason="rate_limited")
        if status == 401:
            budget.tripped = "unauthorized"
            return ApiResult("unavailable", status, reason="unauthorized")
        if status == 403:
            return ApiResult("absent", status, reason="forbidden")
        if status == 404:
            return ApiResult("absent", status, reason="not_found")
        if status == 410:
            return ApiResult("absent", status, reason="gone")
        if status == 451:
            return ApiResult("absent", status, reason="blocked_by_policy")
        if status == 422:
            return ApiResult("absent", status, reason="unprocessable")
        if status in _REDIRECTS:
            return ApiResult("unavailable", status, reason="redirected")
        if status >= 500:
            return ApiResult("unavailable", status, reason="server_error")
        return ApiResult("unavailable", status, reason=f"http_{status}")


def _is_rate_limited(response: HttpResponse) -> bool:
    """GitHub signals a rate limit with 429, or 403 plus one of three markers."""
    if response.status == 429:
        return True
    headers = response.headers
    if headers.get("retry-after"):
        return True
    if headers.get("x-ratelimit-remaining") == "0":
        return True
    snippet = response.body[:2000].decode("utf-8", "ignore").lower()
    return "rate limit" in snippet or "abuse detection" in snippet


__all__ = [
    "MAX_RESPONSE_BYTES",
    "ApiResult",
    "CallBudget",
    "EtagCache",
    "GitHubRestReader",
    "HttpResponse",
    "HttpTransport",
    "TransportError",
    "UrllibTransport",
]
