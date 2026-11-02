"""HTTP hardening middleware (PRD-11): headers, body limits, rate limits."""

from radius_api.middleware.client_ip import parse_trusted_proxies, resolve_client_ip
from radius_api.middleware.rate_limit import (
    InMemoryRateLimitStore,
    RateLimitDecision,
    RateLimiter,
    RateLimitMiddleware,
    RateLimitStore,
    build_rate_limiter,
    classify_request,
)
from radius_api.middleware.request_limits import RequestLimitsMiddleware
from radius_api.middleware.security_headers import SecurityHeadersMiddleware

__all__ = [
    "InMemoryRateLimitStore",
    "RateLimitDecision",
    "RateLimitMiddleware",
    "RateLimitStore",
    "RateLimiter",
    "RequestLimitsMiddleware",
    "SecurityHeadersMiddleware",
    "build_rate_limiter",
    "classify_request",
    "parse_trusted_proxies",
    "resolve_client_ip",
]
