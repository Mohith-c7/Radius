"""GitHub REST rate-limit handling: classification, bounded waits and clear errors.

GitHub documents two kinds of limit (https://docs.github.com/rest/using-the-rest-api/rate-limits-for-the-rest-api):

* **primary**: a quota per hour. The response carries ``x-ratelimit-remaining`` and
  ``x-ratelimit-reset`` (epoch seconds). An exhausted quota answers 403 (or 429) with
  ``x-ratelimit-remaining: 0``.
* **secondary** (abuse): too many requests too fast or too many concurrent ones. The response is
  403 or 429, usually with ``retry-after`` (seconds) and a message mentioning "secondary rate
  limit" or "abuse detection".

A 403 without any of those markers is a permission problem and is never retried.

Safety rules implemented by :class:`RetryPolicy` and the client:

* A rate-limited response was rejected before it did any work, so even a POST can be retried.
* A 5xx or a network error may have happened after the server acted. Only idempotent methods are
  retried for those; POST never is.
* Retries are bounded by ``max_attempts`` and by ``max_total_wait_seconds``. A wait that does not
  fit the remaining budget is not slept at all: the call fails at once with
  :class:`GitHubRateLimitError`, which tells the caller how long GitHub asked to wait.
* Every sleep gets random jitter so that several workers do not retry in lockstep.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from radius_shared.errors import AccessDeniedError

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"})
TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})
_SECONDARY_MARKERS = ("secondary rate limit", "abuse detection", "abuse rate limit")
_PRIMARY_MARKERS = ("api rate limit exceeded", "rate limit exceeded")
_MAX_MESSAGE_CHARS = 300
#: GitHub asks for at least a minute after a secondary limit when it gives no retry-after.
SECONDARY_DEFAULT_WAIT = 60.0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounds for retrying one request."""

    max_attempts: int = 4
    max_total_wait_seconds: float = 60.0
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    #: Extra random wait, as a fraction of the wait (0.2 adds 0 to 20 percent).
    jitter_fraction: float = 0.2
    retry_server_errors: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            msg = "max_attempts must be at least 1."
            raise ValueError(msg)
        if self.max_total_wait_seconds < 0 or self.base_backoff_seconds < 0:
            msg = "waits must not be negative."
            raise ValueError(msg)

    @classmethod
    def disabled(cls) -> RetryPolicy:
        return cls(max_attempts=1, max_total_wait_seconds=0.0)


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """What the response headers say about the quota (all optional)."""

    limit: int | None = None
    remaining: int | None = None
    reset_epoch: float | None = None
    resource: str | None = None
    retry_after: float | None = None


class GitHubRateLimitError(AccessDeniedError):
    """GitHub refused the call because of a rate limit and retrying did not help (or was not allowed)."""

    code = "GITHUB_RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        retry_after_seconds: float | None,
        attempts: int,
        waited_seconds: float,
    ) -> None:
        super().__init__(message, code=self.code)
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds
        self.attempts = attempts
        self.waited_seconds = waited_seconds


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    if value is None and isinstance(headers, Mapping):
        lowered = name.lower()
        for key, item in headers.items():
            if str(key).lower() == lowered:
                value = item
                break
    return None if value is None else str(value).strip()


def _number(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return (
        parsed if parsed >= 0 and parsed == parsed and parsed != float("inf") else None
    )


def parse_rate_limit(headers: Any) -> RateLimitInfo:
    """Read the rate-limit headers; absent or malformed values become ``None``."""

    limit = _number(_header(headers, "x-ratelimit-limit"))
    remaining = _number(_header(headers, "x-ratelimit-remaining"))
    return RateLimitInfo(
        limit=None if limit is None else int(limit),
        remaining=None if remaining is None else int(remaining),
        reset_epoch=_number(_header(headers, "x-ratelimit-reset")),
        resource=_header(headers, "x-ratelimit-resource"),
        retry_after=_number(_header(headers, "retry-after")),
    )


def classify_rate_limit(status: int, headers: Any, body: str) -> str | None:
    """Return ``"primary"``, ``"secondary"`` or ``None`` (not a rate limit)."""

    if status not in (403, 429):
        return None
    info = parse_rate_limit(headers)
    text = body[:2000].lower()
    if any(marker in text for marker in _SECONDARY_MARKERS):
        return "secondary"
    if info.remaining == 0:
        return "primary"
    if info.retry_after is not None:
        return "secondary"
    if any(marker in text for marker in _PRIMARY_MARKERS):
        return "primary"
    if status == 429:
        return "secondary"
    return None


def wait_for_rate_limit(
    kind: str, info: RateLimitInfo, now: float, attempt: int
) -> float:
    """Seconds GitHub wants us to wait, before jitter."""

    if info.retry_after is not None:
        return info.retry_after
    if kind == "primary" and info.reset_epoch is not None:
        return max(0.0, info.reset_epoch - now) + 1.0
    if kind == "secondary":
        return SECONDARY_DEFAULT_WAIT * attempt
    return 1.0


def backoff(policy: RetryPolicy, attempt: int) -> float:
    """Exponential backoff for transient failures (``attempt`` starts at 1)."""

    return min(
        policy.max_backoff_seconds, policy.base_backoff_seconds * (2 ** (attempt - 1))
    )


def short_message(body: str) -> str:
    """The ``message`` field of a GitHub error body, bounded; falls back to the raw text."""

    text = body
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
            text = parsed["message"]
    except ValueError:
        pass
    text = " ".join(text.split())
    return (
        text if len(text) <= _MAX_MESSAGE_CHARS else text[:_MAX_MESSAGE_CHARS] + "..."
    )


__all__ = [
    "IDEMPOTENT_METHODS",
    "TRANSIENT_STATUSES",
    "GitHubRateLimitError",
    "RateLimitInfo",
    "RetryPolicy",
    "backoff",
    "classify_rate_limit",
    "parse_rate_limit",
    "short_message",
    "wait_for_rate_limit",
]
