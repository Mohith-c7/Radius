"""Wire CORS, body limits and rate limiting onto the app (innermost layers)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from radius_shared.config import RuntimeEnvironment

from radius_api.config import ApiSettings, split_csv
from radius_api.middleware.rate_limit import (
    RateLimiter,
    RateLimitMiddleware,
    RateLimitStore,
    build_rate_limiter,
)
from radius_api.middleware.request_limits import BodyLimits, RequestLimitsMiddleware

LOCAL_DASHBOARD_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
)

#: Exactly the request headers the API and dashboard use; never "*".
CORS_ALLOW_HEADERS = (
    "Authorization",
    "Content-Type",
    "Accept",
    "If-Match",
    "Idempotency-Key",
    "X-Request-ID",
    "X-Radius-Organization-Id",
    "X-Radius-API-Key",
    "X-Radius-Actor",
    "X-Analysis-Id",
)
CORS_ALLOW_METHODS = ("GET", "POST", "PATCH", "DELETE", "OPTIONS")
CORS_EXPOSE_HEADERS = (
    "ETag",
    "X-Request-ID",
    "Retry-After",
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "RateLimit-Policy",
)


def resolve_cors_origins(settings: ApiSettings) -> list[str]:
    """Allowed origins: configured ones, plus localhost outside production."""

    origins = split_csv(settings.cors_origins)
    if settings.environment != RuntimeEnvironment.PRODUCTION:
        origins = [*LOCAL_DASHBOARD_ORIGINS, *origins]
    return list(dict.fromkeys(origins))


def install_http_hardening(
    app: FastAPI,
    settings: ApiSettings,
    *,
    rate_limit_store: RateLimitStore | None = None,
) -> RateLimiter:
    """Install CORS (outer), body limits, then rate limiting (inner).

    Add order is innermost first. CORS sits outside the limiters so preflights
    are answered without consuming tokens and 413/429 replies still carry CORS
    headers the browser can read.
    """

    limiter = build_rate_limiter(settings, rate_limit_store)
    app.state.rate_limiter = limiter
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(
        RequestLimitsMiddleware,
        limits=BodyLimits(
            default=settings.max_body_bytes,
            webhook=settings.webhook_max_body_bytes,
            upload=settings.upload_max_body_bytes,
        ),
    )
    origins = resolve_cors_origins(settings)
    wildcard = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Starlette would reflect any Origin for "*" + credentials; never allow that.
        allow_credentials=settings.cors_allow_credentials and not wildcard,
        allow_methods=list(CORS_ALLOW_METHODS),
        allow_headers=list(CORS_ALLOW_HEADERS),
        expose_headers=list(CORS_EXPOSE_HEADERS),
        max_age=600,
    )
    return limiter
