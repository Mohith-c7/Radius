"""PRD-11: security headers, CORS, body limits, rate limits, proxy trust."""

from __future__ import annotations

import ipaddress
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from radius_api.config import ApiSettings, get_api_settings, parse_rate_spec
from radius_api.main import create_app
from radius_api.middleware import (
    InMemoryRateLimitStore,
    RateLimiter,
    build_rate_limiter,
    classify_request,
    parse_trusted_proxies,
    resolve_client_ip,
)
from radius_api.middleware.hardening import (
    CORS_ALLOW_HEADERS,
    resolve_cors_origins,
)
from radius_shared.observability import metrics as obs_metrics

ORG = "00000000-0000-4000-8000-000000000001"
AUTH = {"X-Radius-Organization-Id": ORG, "X-Radius-API-Key": "k-test-1"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _app(monkeypatch, **env: str):
    base = {
        "RADIUS_ENV": "development",
        "RADIUS_ALLOW_INSECURE_DEV": "true",
        "API_KEYS": f"{ORG}:k-test-1",
    }
    base.update(env)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    get_api_settings.cache_clear()
    return create_app()


def _client(monkeypatch, **env: str) -> TestClient:
    return TestClient(_app(monkeypatch, **env))


def _clock_client(monkeypatch, **env: str) -> tuple[TestClient, FakeClock]:
    app = _app(monkeypatch, **env)
    clock = FakeClock()
    app.state.rate_limiter.store = InMemoryRateLimitStore(clock=clock)
    return TestClient(app), clock


# --- security headers ------------------------------------------------------


def _assert_security_headers(headers) -> None:
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-site"
    assert headers["x-frame-options"] == "DENY"
    assert headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert "camera=()" in headers["permissions-policy"]
    assert headers["cache-control"] == "no-store"


def test_headers_on_success_and_error_responses(monkeypatch) -> None:
    client = _client(monkeypatch)
    ok = client.get("/api/v1/health")
    assert ok.status_code == 200
    _assert_security_headers(ok.headers)
    assert "strict-transport-security" not in ok.headers

    denied = client.get("/api/v1/repositories")  # no org header -> 403 envelope
    assert denied.status_code == 403
    _assert_security_headers(denied.headers)

    missing = client.get("/api/v1/nope")
    assert missing.status_code == 404
    _assert_security_headers(missing.headers)


def test_headers_on_413_415_429(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_RATE_LIMIT_AUTH="1/60")
    too_big = client.post(
        "/api/v1/repositories",
        content=b"x" * (1024 * 1024 + 1),
        headers={**AUTH, "Content-Type": "application/json"},
    )
    wrong_type = client.post(
        "/api/v1/repositories", content=b"a=b", headers={**AUTH, "Content-Type": "text/plain"}
    )
    client.post("/api/v1/auth/login", json={})
    throttled = client.post("/api/v1/auth/login", json={})
    assert (too_big.status_code, wrong_type.status_code, throttled.status_code) == (
        413,
        415,
        429,
    )
    for response in (too_big, wrong_type, throttled):
        _assert_security_headers(response.headers)


def test_handler_cache_control_is_not_overwritten(monkeypatch) -> None:
    app = _app(monkeypatch)

    @app.get("/_probe")
    def probe():
        from fastapi.responses import JSONResponse

        return JSONResponse({}, headers={"Cache-Control": "private, max-age=5"})

    response = TestClient(app).get("/_probe")
    assert response.headers["cache-control"] == "private, max-age=5"


def test_hsts_only_when_enabled(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_HSTS_ENABLED="true", RADIUS_HSTS_MAX_AGE="600")
    response = client.get("/api/v1/health")
    assert response.headers["strict-transport-security"] == (
        "max-age=600; includeSubDomains"
    )


def test_docs_pages_get_relaxed_csp_but_not_unsafe_default(monkeypatch) -> None:
    client = _client(monkeypatch)
    docs = client.get("/docs")
    assert docs.status_code == 200
    csp = docs.headers["content-security-policy"]
    allowed_hosts = {"https://cdn.jsdelivr.net"}
    assert allowed_hosts <= set(csp.replace(";", " ").split())
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" in csp
    spec = client.get("/openapi.json")
    assert spec.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )


# --- CORS ------------------------------------------------------------------


def _preflight(client, origin: str, method: str = "POST", headers: str = "content-type"):
    return client.options(
        "/api/v1/repositories",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_cors_preflight_matrix(monkeypatch) -> None:
    client = _client(monkeypatch, CORS_ORIGINS="https://app.example.com")
    allowed = _preflight(
        client,
        "https://app.example.com",
        "PATCH",
        "if-match, idempotency-key, x-radius-api-key, x-radius-actor",
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-headers" in allowed.headers
    assert "*" not in allowed.headers["access-control-allow-headers"]
    assert "*" not in allowed.headers["access-control-allow-methods"]

    local = _preflight(client, "http://localhost:3000")
    assert local.status_code == 200

    bad_origin = _preflight(client, "https://evil.example.com")
    assert bad_origin.status_code == 400
    assert "access-control-allow-origin" not in bad_origin.headers

    bad_header = _preflight(client, "https://app.example.com", headers="x-evil")
    assert bad_header.status_code == 400

    bad_method = _preflight(client, "https://app.example.com", method="PUT")
    assert bad_method.status_code == 400


def test_cors_exposes_etag_and_rate_limit_headers(monkeypatch) -> None:
    client = _client(monkeypatch, CORS_ORIGINS="https://app.example.com")
    response = client.get("/api/v1/health", headers={"Origin": "https://app.example.com"})
    exposed = response.headers["access-control-expose-headers"]
    for name in ("ETag", "Retry-After", "RateLimit-Remaining", "X-Request-ID"):
        assert name in exposed


def test_cors_headers_on_429_so_browser_can_read_it(monkeypatch) -> None:
    client = _client(
        monkeypatch, CORS_ORIGINS="https://app.example.com", RADIUS_RATE_LIMIT_AUTH="1/60"
    )
    origin = {"Origin": "https://app.example.com"}
    client.post("/api/v1/auth/login", json={}, headers=origin)
    throttled = client.post("/api/v1/auth/login", json={}, headers=origin)
    assert throttled.status_code == 429
    assert throttled.headers["access-control-allow-origin"] == "https://app.example.com"


def test_production_origins_are_exact_and_exclude_localhost(monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", "p" * 40)
    get_api_settings.cache_clear()
    origins = resolve_cors_origins(get_api_settings())
    assert origins == ["https://app.example.com"]
    dev = ApiSettings(RADIUS_ENV="development", CORS_ORIGINS="https://a.test")
    assert "http://localhost:3000" in resolve_cors_origins(dev)


def test_credentials_never_combined_with_wildcard(monkeypatch) -> None:
    client = _client(monkeypatch, CORS_ORIGINS="*")
    response = client.get("/api/v1/health", headers={"Origin": "https://x.test"})
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_allow_headers_cover_headers_the_api_reads() -> None:
    for name in (
        "Authorization",
        "Content-Type",
        "If-Match",
        "Idempotency-Key",
        "X-Radius-Organization-Id",
        "X-Radius-API-Key",
        "X-Radius-Actor",
        "X-Analysis-Id",
    ):
        assert name in CORS_ALLOW_HEADERS


# --- config validation -----------------------------------------------------


@pytest.mark.parametrize(
    "origins",
    ["*", "https://ok.example.com,*", "http://app.example.com", "https://*.example.com"],
)
def test_production_rejects_wildcard_and_plain_http_origins(origins: str) -> None:
    with pytest.raises(PydanticValidationError):
        ApiSettings(
            RADIUS_ENV="production", CORS_ORIGINS=origins, RADIUS_API_KEY_PEPPER="p" * 40
        )


def test_malformed_origin_rejected_everywhere() -> None:
    for bad in ("app.example.com", "https://a.test/path", "ftp://a.test"):
        with pytest.raises(PydanticValidationError):
            ApiSettings(RADIUS_ENV="development", CORS_ORIGINS=bad)


def test_production_accepts_https_origins() -> None:
    settings = ApiSettings(
        RADIUS_ENV="production",
        CORS_ORIGINS="https://a.example.com, https://b.example.com:8443",
        RADIUS_API_KEY_PEPPER="p" * 40,
    )
    assert resolve_cors_origins(settings) == [
        "https://a.example.com",
        "https://b.example.com:8443",
    ]


@pytest.mark.parametrize("spec", ["", "10", "0/60", "10/0", "a/b", "10/60/1", "-1/60"])
def test_invalid_rate_specs_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_rate_spec(spec)
    with pytest.raises(PydanticValidationError):
        ApiSettings(RADIUS_RATE_LIMIT_GENERAL=spec)


def test_invalid_trusted_proxy_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        ApiSettings(RADIUS_TRUSTED_PROXIES="not-an-ip")


def test_rate_spec_parsing() -> None:
    assert parse_rate_spec(" 120/30 ") == (120, 30)


# --- body limits -----------------------------------------------------------


def test_declared_oversize_body_gets_413_envelope(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_MAX_BODY_BYTES="2048")
    response = client.post(
        "/api/v1/repositories",
        content=b"{" + b" " * 4096 + b"}",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert body["meta"]["max_bytes"] == 2048


def test_chunked_oversize_body_gets_413_not_400(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_MAX_BODY_BYTES="2048")

    def chunks():
        for _ in range(8):
            yield b" " * 1024

    response = client.post(
        "/api/v1/repositories",
        content=chunks(),
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_body_at_limit_is_accepted(monkeypatch) -> None:
    client = _client(monkeypatch, RADIUS_MAX_BODY_BYTES="2048")
    response = client.post(
        "/api/v1/repositories",
        content=b" " * 2048,
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert response.status_code != 413


def test_invalid_content_length_is_400() -> None:
    import asyncio

    from radius_api.middleware.request_limits import BodyLimits, RequestLimitsMiddleware

    sent: list[dict] = []

    async def app(scope, receive, send):  # pragma: no cover - must not be reached
        raise AssertionError

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"content-length", b"abc")],
    }
    middleware = RequestLimitsMiddleware(app, limits=BodyLimits(10, 10, 10))
    asyncio.run(middleware(scope, None, send))
    assert sent[0]["status"] == 400


def test_webhook_has_larger_limit_than_default(monkeypatch) -> None:
    client = _client(
        monkeypatch,
        RADIUS_MAX_BODY_BYTES="2048",
        RADIUS_WEBHOOK_MAX_BODY_BYTES="8192",
        GITHUB_WEBHOOK_SECRET="s",
    )
    headers = {"X-GitHub-Event": "ping", "X-GitHub-Delivery": str(uuid4())}
    mid = client.post("/api/v1/webhooks/github", content=b"x" * 4096, headers=headers)
    assert mid.status_code != 413  # over the default cap, under the webhook cap
    big = client.post("/api/v1/webhooks/github", content=b"x" * 9000, headers=headers)
    assert big.status_code == 413


def test_upload_route_has_its_own_limit_and_accepts_xml(monkeypatch) -> None:
    client = _client(
        monkeypatch, RADIUS_MAX_BODY_BYTES="2048", RADIUS_UPLOAD_MAX_BODY_BYTES="8192"
    )
    url = f"/api/v1/analyses/{uuid4()}/tests/results"
    xml = {**AUTH, "Content-Type": "application/xml"}
    mid = client.post(url, content=b"<a/>" * 1024, headers=xml)
    assert mid.status_code not in (413, 415)
    big = client.post(url, content=b"<a/>" * 4096, headers=xml)
    assert big.status_code == 413


def test_intent_cap_composes_with_global_cap(monkeypatch) -> None:
    from radius_api.routes.intent import MAX_BODY_BYTES

    assert MAX_BODY_BYTES < ApiSettings().max_body_bytes
    client = _client(monkeypatch)
    url = f"/api/v1/analyses/{uuid4()}/intent/sources"
    response = client.post(
        url,
        content=b"{" + b" " * (MAX_BODY_BYTES + 10) + b"}",
        headers={**AUTH, "Content-Type": "application/json", "X-Radius-Actor": "t"},
    )
    # The route's own (stricter) cap answers first; the global cap is not hit.
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert response.status_code != 413


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/plain", 415),
        ("application/xml", 415),
        ("", 415),
        ("application/json", None),
        ("application/json; charset=utf-8", None),
        ("application/vnd.api+json", None),
        ("APPLICATION/JSON", None),
    ],
)
def test_content_type_matrix(monkeypatch, content_type: str, expected: int | None) -> None:
    client = _client(monkeypatch)
    headers = dict(AUTH)
    if content_type:
        headers["Content-Type"] = content_type
    response = client.post("/api/v1/repositories", content=b"{}", headers=headers)
    if expected is None:
        assert response.status_code != 415
    else:
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_bodyless_and_get_requests_skip_content_type_check(monkeypatch) -> None:
    client = _client(monkeypatch)
    assert client.get("/api/v1/health").status_code == 200
    rerun = client.post(f"/api/v1/analyses/{uuid4()}/rerun", headers=AUTH)
    assert rerun.status_code != 415


# --- rate limiting ---------------------------------------------------------


def test_burst_then_429_with_correct_retry_after(monkeypatch) -> None:
    client, clock = _clock_client(monkeypatch, RADIUS_RATE_LIMIT_AUTH="3/60")
    for remaining in (2, 1, 0):
        ok = client.post("/api/v1/auth/login", json={})
        assert ok.status_code != 429
        assert ok.headers["ratelimit-limit"] == "3"
        assert ok.headers["ratelimit-remaining"] == str(remaining)
        assert ok.headers["ratelimit-policy"] == "3;w=60"
    denied = client.post("/api/v1/auth/login", json={})
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "20"  # 1 token / (3 per 60s)
    assert denied.headers["ratelimit-remaining"] == "0"
    body = denied.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["meta"] == {"retry_after_seconds": 20, "bucket": "auth"}

    clock.advance(19)
    assert client.post("/api/v1/auth/login", json={}).status_code == 429
    clock.advance(1)
    assert client.post("/api/v1/auth/login", json={}).status_code != 429
    assert client.post("/api/v1/auth/login", json={}).status_code == 429


def test_refill_is_capped_at_capacity(monkeypatch) -> None:
    client, clock = _clock_client(monkeypatch, RADIUS_RATE_LIMIT_AUTH="2/60")
    client.post("/api/v1/auth/login", json={})
    clock.advance(10_000)
    first = client.post("/api/v1/auth/login", json={})
    assert first.headers["ratelimit-remaining"] == "1"


def test_per_key_isolation(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch, RADIUS_RATE_LIMIT_GENERAL="2/60", RADIUS_RATE_LIMIT_IP_MULTIPLIER="100"
    )
    one = {**AUTH}
    two = {"X-Radius-Organization-Id": ORG, "X-Radius-API-Key": "k-other"}
    assert client.get("/api/v1/repositories", headers=one).status_code != 429
    assert client.get("/api/v1/repositories", headers=one).status_code != 429
    assert client.get("/api/v1/repositories", headers=one).status_code == 429
    # A different key has its own bucket even from the same IP.
    assert client.get("/api/v1/repositories", headers=two).status_code != 429


def test_rotating_bogus_keys_still_hits_ip_limit(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch, RADIUS_RATE_LIMIT_GENERAL="2/60", RADIUS_RATE_LIMIT_IP_MULTIPLIER="2"
    )
    statuses = [
        client.get(
            "/api/v1/repositories",
            headers={"X-Radius-Organization-Id": ORG, "X-Radius-API-Key": f"bogus-{i}"},
        ).status_code
        for i in range(6)
    ]
    assert statuses[:4] == [403] * 4
    assert statuses[4:] == [429, 429]


def test_buckets_are_separate(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch,
        RADIUS_RATE_LIMIT_AUTH="1/60",
        RADIUS_RATE_LIMIT_EXPENSIVE="1/60",
        RADIUS_RATE_LIMIT_GENERAL="50/60",
    )
    assert client.post("/api/v1/auth/login", json={}).status_code != 429
    assert client.post("/api/v1/auth/login", json={}).status_code == 429
    # auth exhausted, general and expensive still available
    assert client.get("/api/v1/repositories", headers=AUTH).status_code != 429
    rerun = f"/api/v1/analyses/{uuid4()}/rerun"
    assert client.post(rerun, headers=AUTH).status_code != 429
    expensive = client.post(rerun, headers=AUTH)
    assert expensive.status_code == 429
    assert expensive.json()["meta"]["bucket"] == "expensive"
    assert client.get("/api/v1/repositories", headers=AUTH).status_code != 429


def test_health_and_ready_never_limited(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch, RADIUS_RATE_LIMIT_GENERAL="1/60", RADIUS_RATE_LIMIT_IP_MULTIPLIER="1"
    )
    for _ in range(20):
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/ready").status_code == 200
    assert "ratelimit-limit" not in client.get("/api/v1/health").headers


def test_preflight_does_not_consume_tokens(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch,
        CORS_ORIGINS="https://app.example.com",
        RADIUS_RATE_LIMIT_GENERAL="1/60",
        RADIUS_RATE_LIMIT_IP_MULTIPLIER="1",
    )
    for _ in range(5):
        assert _preflight(client, "https://app.example.com").status_code == 200
    assert client.get("/api/v1/repositories", headers=AUTH).status_code != 429


def test_webhook_bucket_is_generous_and_separate(monkeypatch) -> None:
    client, _ = _clock_client(
        monkeypatch, RADIUS_RATE_LIMIT_GENERAL="1/60", GITHUB_WEBHOOK_SECRET="s"
    )
    headers = {"X-GitHub-Event": "ping", "X-GitHub-Delivery": str(uuid4())}
    for _ in range(30):
        response = client.post("/api/v1/webhooks/github", content=b"{}", headers=headers)
        assert response.status_code != 429


def test_rate_limiting_can_be_disabled(monkeypatch) -> None:
    client = _client(
        monkeypatch, RADIUS_RATE_LIMIT_ENABLED="false", RADIUS_RATE_LIMIT_AUTH="1/60"
    )
    for _ in range(5):
        response = client.post("/api/v1/auth/login", json={})
        assert response.status_code != 429
        assert "ratelimit-limit" not in response.headers


def test_limiter_failure_fails_open_and_logs(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import radius_api.middleware.rate_limit as rate_limit_module

    logger = MagicMock()
    monkeypatch.setattr(rate_limit_module, "LOGGER", logger)
    app = _app(monkeypatch)

    class Broken:
        def consume(self, key, capacity, window):
            raise RuntimeError("store down")

    app.state.rate_limiter.store = Broken()
    client = TestClient(app)
    response = client.get("/api/v1/repositories", headers=AUTH)
    assert response.status_code == 200
    logger.exception.assert_called_once()


def test_throttle_increments_metric(monkeypatch) -> None:
    try:
        client, _ = _clock_client(monkeypatch, RADIUS_RATE_LIMIT_AUTH="1/60")
        # the app factory resets metrics from settings; enable after it is built
        obs_metrics.configure_metrics(True)
        if not obs_metrics.metrics_enabled():
            pytest.skip("prometheus_client not installed")
        client.post("/api/v1/auth/login", json={})
        client.post("/api/v1/auth/login", json={})
        payload, _ = obs_metrics.render_metrics()
        assert b'radius_http_rate_limited_total{bucket="auth"} 1.0' in payload
    finally:
        obs_metrics.configure_metrics(False)


def test_metric_noop_when_disabled() -> None:
    obs_metrics.configure_metrics(False)
    obs_metrics.record_rate_limited("auth")  # must not raise


# --- classification and store ---------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "bucket"),
    [
        ("GET", "/api/v1/health", None),
        ("GET", "/api/v1/ready", None),
        ("GET", "/health", None),
        ("GET", "/metrics", None),
        ("OPTIONS", "/api/v1/repositories", None),
        ("POST", "/api/v1/auth/login", "auth"),
        ("POST", "/api/v1/auth/forgot-password", "auth"),
        ("GET", "/api/v1/auth/oauth/github", "auth"),
        ("GET", "/api/v1/auth/me", "general"),
        ("POST", "/api/v1/auth/refresh", "auth"),
        ("POST", "/api/v1/auth/logout", "general"),
        ("POST", "/api/v1/webhooks/github", "webhook"),
        ("POST", "/api/v1/webhooks/github/", "webhook"),
        ("POST", "/api/v1/analyses", "expensive"),
        ("GET", "/api/v1/analyses", "general"),
        ("POST", "/api/v1/analyses/abc/rerun", "expensive"),
        ("POST", "/api/v1/analyses/abc/intent/rebuild", "expensive"),
        ("POST", "/api/v1/analyses/abc/intent/sources", "expensive"),
        ("POST", "/api/v1/analyses/abc/tests/results", "expensive"),
        ("POST", "/api/v1/repositories/r/sync-pull-requests", "expensive"),
        ("GET", "/api/v1/analyses/abc/intent", "general"),
        ("GET", "/api/v1/repositories", "general"),
    ],
)
def test_classification(method: str, path: str, bucket: str | None) -> None:
    assert classify_request(method, path) == bucket


def test_store_evicts_least_recently_used() -> None:
    clock = FakeClock()
    store = InMemoryRateLimitStore(clock=clock, max_keys=10)
    for i in range(11):
        store.consume(f"k{i}", 5, 60)
    assert len(store) <= 10
    # k0 was evicted, so its bucket starts full again.
    assert store.consume("k0", 5, 60).remaining == 4


def test_store_decision_fields() -> None:
    clock = FakeClock()
    store = InMemoryRateLimitStore(clock=clock)
    first = store.consume("a", 4, 40)  # 0.1 token/s
    assert (first.allowed, first.remaining, first.reset, first.retry_after) == (
        True,
        3,
        10,
        0,
    )
    for _ in range(3):
        store.consume("a", 4, 40)
    denied = store.consume("a", 4, 40)
    assert denied.allowed is False and denied.retry_after == 10


def test_limiter_disabled_and_exempt_return_none() -> None:
    store = InMemoryRateLimitStore()
    limiter = RateLimiter(store, {"general": (1, 60)}, enabled=False)
    scope = {"method": "GET", "path": "/api/v1/repositories", "headers": []}
    assert limiter.evaluate(scope) is None
    limiter.enabled = True
    assert limiter.evaluate({**scope, "path": "/api/v1/health"}) is None


def test_build_rate_limiter_reads_settings() -> None:
    settings = ApiSettings(
        RADIUS_RATE_LIMIT_GENERAL="7/9", RADIUS_TRUSTED_PROXIES="10.0.0.0/8"
    )
    limiter = build_rate_limiter(settings)
    assert limiter.policies["general"] == (7, 9)
    assert limiter.trusted_proxies == [ipaddress.ip_network("10.0.0.0/8")]


# --- trusted proxy matrix --------------------------------------------------


def _scope(peer: str | None, *xff: str) -> dict:
    return {
        "client": (peer, 1234) if peer else None,
        "headers": [(b"x-forwarded-for", value.encode()) for value in xff],
    }


TRUSTED = parse_trusted_proxies(["10.0.0.0/8", "fd00::/8"])


@pytest.mark.parametrize(
    ("scope", "trusted", "expected"),
    [
        (_scope("203.0.113.9", "1.2.3.4"), [], "203.0.113.9"),  # no proxies: ignore XFF
        (_scope("203.0.113.9", "1.2.3.4"), TRUSTED, "203.0.113.9"),  # untrusted peer
        (_scope("10.0.0.5", "198.51.100.7"), TRUSTED, "198.51.100.7"),
        (_scope("10.0.0.5", "6.6.6.6, 198.51.100.7"), TRUSTED, "198.51.100.7"),  # spoof prefix
        (_scope("10.0.0.5", "198.51.100.7, 10.1.1.1"), TRUSTED, "198.51.100.7"),  # chain
        (_scope("10.0.0.5", "10.2.2.2, 10.1.1.1"), TRUSTED, "10.2.2.2"),  # all trusted
        (_scope("10.0.0.5", "garbage"), TRUSTED, "10.0.0.5"),
        (_scope("10.0.0.5", "198.51.100.7, garbage"), TRUSTED, "10.0.0.5"),
        (_scope("10.0.0.5"), TRUSTED, "10.0.0.5"),  # trusted, no header
        (_scope("10.0.0.5", "1.1.1.1", "2.2.2.2"), TRUSTED, "2.2.2.2"),  # repeated headers
        (_scope("fd00::1", "2001:db8::5"), TRUSTED, "2001:db8::5"),
        (_scope("testclient", "1.2.3.4"), TRUSTED, "testclient"),  # non-IP peer
        (_scope(None), TRUSTED, "unknown"),
    ],
)
def test_client_ip_resolution(scope, trusted, expected) -> None:
    assert resolve_client_ip(scope, trusted) == expected


def test_rate_limit_uses_forwarded_ip_only_from_trusted_proxy(monkeypatch) -> None:
    # TestClient peer is "testclient" (not an IP) so XFF must be ignored.
    client, _ = _clock_client(
        monkeypatch, RADIUS_RATE_LIMIT_AUTH="1/60", RADIUS_TRUSTED_PROXIES="10.0.0.0/8"
    )
    first = client.post("/api/v1/auth/login", json={}, headers={"X-Forwarded-For": "1.1.1.1"})
    second = client.post("/api/v1/auth/login", json={}, headers={"X-Forwarded-For": "2.2.2.2"})
    assert first.status_code != 429
    assert second.status_code == 429  # spoofed header did not buy a fresh bucket


def test_error_envelope_shape_is_stable() -> None:
    from radius_api.middleware.errors import error_envelope

    response = error_envelope(429, "X", "msg", meta={"a": 1})
    assert json.loads(response.body) == {
        "success": False,
        "data": None,
        "error": {"code": "X", "message": "msg"},
        "meta": {"a": 1},
    }
