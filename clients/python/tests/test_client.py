"""Client tests against an in-process fake transport (no network)."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from radius_client import (
    ApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    RadiusClient,
    RateLimitedError,
    ServerError,
    StaleEtagError,
    TransportError,
    TransportResponse,
    ValidationFailedError,
    Versioned,
    parse_retry_after,
)

ORG = "5f1c9a1e-3a63-4a52-9d50-6a1f0c2b7d11"
KEY = "k" + "-test-" + "0" * 6  # built at runtime, not a real secret


def ok(data, status=200, **headers) -> TransportResponse:
    body = json.dumps({"success": True, "data": data, "error": None, "meta": {}})
    return TransportResponse(status, {k.lower(): v for k, v in headers.items()}, body.encode())


def fail(status, code, message="boom", **headers) -> TransportResponse:
    body = json.dumps({"success": False, "data": None, "error": {"code": code, "message": message}})
    return TransportResponse(status, {k.lower(): v for k, v in headers.items()}, body.encode())


class FakeTransport:
    """Replays queued responses (or raises queued exceptions) and records requests."""

    def __init__(self, *responses: TransportResponse | Exception) -> None:
        self.queue = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, headers: Mapping[str, str], body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(*responses, **kwargs) -> tuple[RadiusClient, FakeTransport, list[float]]:
    transport = FakeTransport(*responses)
    sleeps: list[float] = []
    client = RadiusClient(
        "https://radius.test/",
        ORG,
        KEY,
        transport=transport,
        sleep=sleeps.append,
        **kwargs,
    )
    return client, transport, sleeps


def test_get_analysis_sends_credentials_and_unwraps_data() -> None:
    client, transport, _ = make(ok({"id": "a1", "status": "pending", "future_field": 1}))
    analysis = client.get_analysis("a1")
    assert analysis["future_field"] == 1  # unknown fields are preserved
    call = transport.calls[0]
    assert call["url"] == "https://radius.test/api/v1/analyses/a1"
    assert call["headers"]["X-Radius-Organization-Id"] == ORG
    assert call["headers"]["X-Radius-API-Key"] == KEY
    assert KEY not in repr(client)


def test_list_analyses_encodes_only_given_filters() -> None:
    client, transport, _ = make(ok([]))
    assert client.list_analyses(repository_id="r 1", status="completed") == []
    assert transport.calls[0]["url"].endswith(
        "/api/v1/analyses?repositoryId=r+1&status=completed"
    )


def test_path_segments_are_encoded() -> None:
    client, transport, _ = make(ok({"id": "x"}))
    client.get_analysis("../admin?x=1")
    assert transport.calls[0]["url"].endswith("/analyses/..%2Fadmin%3Fx%3D1")


def test_lookup_and_confidence() -> None:
    client, transport, _ = make(ok({"id": "a1"}), ok({"verification_status": "verified"}))
    client.lookup_analysis(pull_request=7, commit_sha="abc1234", repository="acme/radius")
    assert "pullRequest=7&commitSha=abc1234&repository=acme%2Fradius" in transport.calls[0]["url"]
    assert client.get_confidence("a1")["verification_status"] == "verified"


def test_upload_test_results_sends_raw_body_and_commit() -> None:
    client, transport, _ = make(ok({"id": "u1", "passed": 3}))
    result = client.upload_test_results("a1", "<testsuite/>", commit_sha="a" * 40)
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/analyses/a1/tests/results?commit_sha={'a' * 40}")
    assert call["body"] == b"<testsuite/>"
    assert call["headers"]["Content-Type"] == "application/xml"
    assert result["passed"] == 3


def test_intent_read_returns_etag_and_confirm_sends_if_match() -> None:
    snapshot = {"id": "s1", "etag": '"in-body"', "criteria": []}
    client, transport, _ = make(
        ok(snapshot, ETag='"v1"'),
        ok({"criterion": {"id": "c1", "state": "confirmed"}, "etag": '"v2"'}, ETag='"v2"'),
    )
    read = client.get_intent("a1")
    assert isinstance(read, Versioned) and read.etag == '"v1"'
    result = client.confirm_criterion("a1", "c1", if_match=read, reason="ok")
    assert result.etag == '"v2"'
    call = transport.calls[1]
    assert call["method"] == "PATCH"
    assert call["headers"]["If-Match"] == '"v1"'
    assert json.loads(call["body"]) == {"action": "confirm", "reason": "ok"}
    assert call["headers"]["Content-Type"] == "application/json"


def test_etag_falls_back_to_body_field() -> None:
    client, _, _ = make(ok({"id": "s1", "etag": '"in-body"', "criteria": []}))
    assert client.get_intent("a1").etag == '"in-body"'


@pytest.mark.parametrize(
    ("status", "code", "exc"),
    [
        (403, "FORBIDDEN", AuthError),
        (404, "NOT_FOUND", NotFoundError),
        (409, "CONFLICT", ConflictError),
        (409, "INTENT_STALE", StaleEtagError),
        (422, "VALIDATION_ERROR", ValidationFailedError),
        (500, "INTERNAL", ServerError),
        (418, "TEAPOT", ApiError),
    ],
)
def test_errors_are_typed(status, code, exc) -> None:
    client, _, _ = make(fail(status, code))
    with pytest.raises(exc) as info:
        client.get_confidence("a1")
    assert type(info.value) is exc
    assert info.value.status == status and info.value.code == code
    assert isinstance(info.value, ApiError)


def test_stale_etag_is_a_conflict() -> None:
    assert issubclass(StaleEtagError, ConflictError)


def test_fastapi_validation_detail_is_mapped() -> None:
    body = json.dumps({"detail": [{"msg": "field required", "loc": ["query", "x"]}]}).encode()
    client, _, _ = make(TransportResponse(422, {}, body))
    with pytest.raises(ValidationFailedError) as info:
        client.get_analysis("a1")
    assert info.value.code == "VALIDATION_ERROR" and "field required" in info.value.message


def test_non_envelope_success_is_rejected() -> None:
    client, _, _ = make(TransportResponse(200, {}, b"<html>proxy</html>"))
    with pytest.raises(ApiError) as info:
        client.get_analysis("a1")
    assert info.value.code == "INVALID_RESPONSE"


def test_429_is_retried_honoring_retry_after() -> None:
    client, transport, sleeps = make(
        fail(429, "RATE_LIMITED", **{"Retry-After": "2"}),
        fail(429, "RATE_LIMITED", **{"Retry-After": "5"}),
        ok({"id": "a1"}),
    )
    assert client.get_analysis("a1")["id"] == "a1"
    assert sleeps == [2.0, 5.0]
    assert len(transport.calls) == 3


def test_429_on_post_is_retried_with_the_same_body() -> None:
    client, transport, sleeps = make(
        fail(429, "RATE_LIMITED", **{"Retry-After": "1"}), ok({"id": "u1"})
    )
    client.upload_test_results("a1", b"{}", commit_sha="abc1234", content_type="application/json")
    assert sleeps == [1.0]
    assert transport.calls[0]["body"] == transport.calls[1]["body"] == b"{}"


def test_429_exhausts_retries_then_raises_with_retry_after() -> None:
    client, transport, sleeps = make(
        *[fail(429, "RATE_LIMITED", **{"Retry-After": "1"}) for _ in range(3)], max_retries=2
    )
    with pytest.raises(RateLimitedError) as info:
        client.get_analysis("a1")
    assert info.value.retry_after == 1.0
    assert len(transport.calls) == 3 and sleeps == [1.0, 1.0]


def test_429_longer_than_allowed_is_not_slept_on() -> None:
    client, transport, sleeps = make(
        fail(429, "RATE_LIMITED", **{"Retry-After": "3600"}), max_retry_after=30
    )
    with pytest.raises(RateLimitedError):
        client.get_analysis("a1")
    assert sleeps == [] and len(transport.calls) == 1


def test_429_without_header_uses_exponential_backoff() -> None:
    client, _, sleeps = make(
        fail(429, "RATE_LIMITED"), fail(429, "RATE_LIMITED"), ok({"id": "a1"}),
        backoff_base=0.5,
    )
    client.get_analysis("a1")
    assert sleeps == [0.5, 1.0]


def test_get_retries_transient_5xx_and_connection_errors_but_post_does_not() -> None:
    client, _, sleeps = make(
        fail(503, "UNAVAILABLE"), TransportError("reset"), ok({"id": "a1"})
    )
    assert client.get_analysis("a1")["id"] == "a1"
    assert len(sleeps) == 2

    client, transport, _ = make(fail(503, "UNAVAILABLE"))
    with pytest.raises(ServerError):
        client.upload_test_results("a1", b"x", commit_sha="abc1234")
    assert len(transport.calls) == 1

    client, _, _ = make(TransportError("down"))
    with pytest.raises(TransportError):
        client.upload_test_results("a1", b"x", commit_sha="abc1234")


def test_parse_retry_after_variants() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:30 GMT", now=now) == 30.0
    assert parse_retry_after("Wed, 31 Dec 2025 00:00:00 GMT", now=now) == 0.0
