"""Token-bucket rate limiting (pure ASGI) with a pluggable store.

Buckets (``classify_request``): ``auth`` (credential endpoints, per IP),
``webhook`` (GitHub deliveries, per IP, generous), ``expensive`` (rebuilds,
re-runs, uploads) and ``general``. Key-identified buckets are limited per API
key *and* per IP, so rotating bogus keys does not bypass the limit.

Failure policy: if the store raises, the request is allowed (fail open) and
the error is logged; availability of the API outranks the limiter.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from radius_shared.logging import get_logger
from radius_shared.observability import metrics as obs_metrics
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radius_api.config import ApiSettings, parse_rate_spec, split_csv
from radius_api.middleware.client_ip import (
    Network,
    parse_trusted_proxies,
    resolve_client_ip,
)
from radius_api.middleware.errors import error_envelope
from radius_api.middleware.request_limits import WEBHOOK_PATH

LOGGER = get_logger(__name__)

EXEMPT_PATHS = frozenset(
    {"/health", "/ready", "/api/v1/health", "/api/v1/ready", "/metrics"}
)
_AUTH_PREFIX = "/api/v1/auth/"
_AUTH_UNLIMITED = frozenset({"/api/v1/auth/logout"})
_EXPENSIVE = re.compile(
    r"^/api/v1/(analyses|coverage|"
    r"analyses/[^/]+/(rerun|intent/rebuild|intent/sources|tests/results)|"
    r"repositories/[^/]+/sync-pull-requests)$"
)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of consuming one token."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until a token is available (0 when allowed)
    reset: int  # seconds until the bucket is full again
    window: int


class RateLimitStore(Protocol):
    """Storage seam. Implement this for a shared (Redis/PostgreSQL) store."""

    def consume(self, key: str, capacity: int, window: int) -> RateLimitDecision:
        """Take one token from ``key``'s bucket (capacity per ``window`` seconds)."""


class InMemoryRateLimitStore:
    """Process-local token buckets. Not shared across replicas or restarts."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 100_000,
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._buckets)

    def consume(self, key: str, capacity: int, window: int) -> RateLimitDecision:
        rate = capacity / window
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(float(capacity), tokens + max(0.0, now - last) * rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)
            self._buckets.move_to_end(key)
            if len(self._buckets) > self._max_keys:
                self._evict()
        retry_after = 0 if allowed else max(1, math.ceil((1.0 - tokens) / rate))
        return RateLimitDecision(
            allowed=allowed,
            limit=capacity,
            remaining=int(tokens),
            retry_after=retry_after,
            reset=math.ceil((capacity - tokens) / rate),
            window=window,
        )

    def _evict(self) -> None:
        # Least recently used first. Evicting resets that client's bucket to
        # full, which is the documented cost of bounded memory.
        for _ in range(max(1, self._max_keys // 10)):
            self._buckets.popitem(last=False)


def classify_request(method: str, path: str) -> str | None:
    """Return the bucket name for a request, or ``None`` when exempt."""

    normalized = path.rstrip("/") or "/"
    method = method.upper()
    if method == "OPTIONS" or normalized in EXEMPT_PATHS:
        return None
    if normalized == WEBHOOK_PATH:
        return "webhook"
    if normalized.startswith(_AUTH_PREFIX) and normalized not in _AUTH_UNLIMITED:
        if method == "POST" or normalized.startswith(_AUTH_PREFIX + "oauth/"):
            return "auth"
    if method == "POST" and _EXPENSIVE.match(normalized):
        return "expensive"
    return "general"


class RateLimiter:
    """Policy + store. ``evaluate`` is the only entry point middleware needs."""

    def __init__(
        self,
        store: RateLimitStore,
        policies: dict[str, tuple[int, int]],
        *,
        ip_multiplier: int = 2,
        trusted_proxies: list[Network] | None = None,
        enabled: bool = True,
    ) -> None:
        self.store = store
        # per-process salt: bucket ids are in-memory only (a shared store needs its own keyed id)
        self._fp_salt = secrets.token_hex(16)
        self.policies = policies
        self.ip_multiplier = ip_multiplier
        self.trusted_proxies = trusted_proxies or []
        self.enabled = enabled

    def evaluate(self, scope: Scope) -> tuple[str, RateLimitDecision] | None:
        """Return ``(bucket, decision)`` for the most relevant bucket, or None."""

        if not self.enabled:
            return None
        bucket = classify_request(scope["method"], scope["path"])
        if bucket is None:
            return None
        capacity, window = self.policies[bucket]
        ip = resolve_client_ip(scope, self.trusted_proxies)
        keyed = bucket in {"general", "expensive"}
        ip_capacity = capacity * self.ip_multiplier if keyed else capacity
        ip_decision = self.store.consume(f"{bucket}:ip:{ip}", ip_capacity, window)
        if not ip_decision.allowed:
            return bucket, ip_decision
        api_key = next(
            (v for k, v in scope["headers"] if k == b"x-radius-api-key"), b""
        )
        if keyed and api_key:
            # bucket id: the raw key never reaches the (pluggable) store
            fingerprint = format(hash((self._fp_salt, api_key)) & 0xFFFFFFFFFFFFFFFF, "016x")
            key_decision = self.store.consume(
                f"{bucket}:key:{fingerprint}", capacity, window
            )
            return bucket, key_decision
        return bucket, ip_decision


def build_rate_limiter(
    settings: ApiSettings,
    store: RateLimitStore | None = None,
) -> RateLimiter:
    """Create a limiter from settings (store defaults to in-memory)."""

    policies = {
        "auth": parse_rate_spec(settings.rate_limit_auth),
        "webhook": parse_rate_spec(settings.rate_limit_webhook),
        "general": parse_rate_spec(settings.rate_limit_general),
        "expensive": parse_rate_spec(settings.rate_limit_expensive),
    }
    return RateLimiter(
        store or InMemoryRateLimitStore(),
        policies,
        ip_multiplier=settings.rate_limit_ip_multiplier,
        trusted_proxies=parse_trusted_proxies(split_csv(settings.trusted_proxies)),
        enabled=settings.rate_limit_enabled,
    )


def _headers(decision: RateLimitDecision) -> dict[str, str]:
    # draft-ietf-httpapi-ratelimit-headers (-07 field names) + policy hint.
    return {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset),
        "RateLimit-Policy": f"{decision.limit};w={decision.window}",
    }


class RateLimitMiddleware:
    """Apply a :class:`RateLimiter`; answer 429 with the API error envelope."""

    def __init__(self, app: ASGIApp, *, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            result = self.limiter.evaluate(scope)
        except Exception:  # fail open: a broken limiter must not take the API down
            LOGGER.exception("Rate limiter failed; allowing request")
            result = None
        if result is None:
            await self.app(scope, receive, send)
            return
        bucket, decision = result
        headers = _headers(decision)
        if not decision.allowed:
            obs_metrics.record_rate_limited(bucket)
            LOGGER.warning("Request throttled", extra={"bucket": bucket})
            response = error_envelope(
                429,
                "RATE_LIMITED",
                "Too many requests. Retry after the interval in Retry-After.",
                meta={"retry_after_seconds": decision.retry_after, "bucket": bucket},
                headers={**headers, "Retry-After": str(decision.retry_after)},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for name, value in headers.items():
                    mutable[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
