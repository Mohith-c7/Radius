"""Rate-limit handling of GitHubAppClient with a fake transport (no network, no real sleeping)."""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest
from radius_github import (
    GitHubAppClient,
    GitHubAppSettings,
    GitHubRateLimitError,
    RetryPolicy,
)
from radius_github.rate_limit import classify_rate_limit, parse_rate_limit
from radius_shared.errors import AccessDeniedError, ValidationError

NOW = 1_800_000_000.0
TOKEN = "".join(["tok", "en-", "abc123"])  # built at runtime, not a real secret


def headers(**values: str) -> Message:
    msg = Message()
    for key, value in values.items():
        msg[key.replace("_", "-")] = value
    return msg


class Response:
    def __init__(self, payload: Any, hdrs: Message | None = None) -> None:
        self._payload = json.dumps(payload).encode()
        self.headers = hdrs or Message()

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def http_error(code: int, message: str = "", **hdrs: str) -> urllib.error.HTTPError:
    body = json.dumps({"message": message}).encode()
    return urllib.error.HTTPError(
        "https://api.example/x", code, "err", headers(**hdrs), io.BytesIO(body)
    )


class FakeTransport:
    """Plays a script of responses/exceptions and records the calls."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> Any:
        self.requests.append(request)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class Clock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def make(
    transport: FakeTransport, policy: RetryPolicy | None = None, jitter: float = 0.0
):
    clock = Clock()
    client = GitHubAppClient(
        GitHubAppSettings(GITHUB_APP_ID="1", GITHUB_APP_PRIVATE_KEY="x"),
        opener=transport,
        clock=lambda: NOW,
        retry_policy=policy or RetryPolicy(),
        sleep=clock.sleep,
        rng=lambda: jitter,
    )
    return client, clock


def get(client: GitHubAppClient) -> Any:
    return client.list_issue_comments(token=TOKEN, owner="o", repo="r", issue_number=1)


def post(client: GitHubAppClient) -> Any:
    return client.create_issue_comment(
        token=TOKEN, owner="o", repo="r", issue_number=1, body="b"
    )


def test_success_passes_through_and_records_rate_limit_headers() -> None:
    ok = Response(
        [{"id": 1}],
        headers(x_ratelimit_remaining="4999", x_ratelimit_reset=str(int(NOW) + 60)),
    )
    client, clock = make(FakeTransport(ok))
    assert get(client) == [{"id": 1}]
    assert clock.sleeps == []
    assert client.last_rate_limit is not None
    assert client.last_rate_limit.remaining == 4999


def test_primary_limit_waits_until_reset_then_succeeds() -> None:
    reset = str(int(NOW) + 10)
    t = FakeTransport(
        http_error(
            403,
            "API rate limit exceeded",
            x_ratelimit_remaining="0",
            x_ratelimit_reset=reset,
        ),
        Response([]),
    )
    client, clock = make(t)
    assert get(client) == []
    assert clock.sleeps == [11.0]  # reset in 10s plus one second of slack
    assert len(t.requests) == 2


def test_secondary_limit_honors_retry_after_with_jitter() -> None:
    t = FakeTransport(
        http_error(403, "You have exceeded a secondary rate limit.", retry_after="5"),
        Response([]),
    )
    client, clock = make(t, jitter=0.5)
    get(client)
    assert clock.sleeps == [pytest.approx(5.5)]  # 5s + 20% * 0.5 jitter


def test_429_is_a_rate_limit() -> None:
    t = FakeTransport(
        http_error(429, "slow down", retry_after="2"), Response([{"id": 2}])
    )
    client, clock = make(t)
    assert get(client) == [{"id": 2}]
    assert clock.sleeps == [2.0]


def test_plain_403_is_a_permission_error_and_not_retried() -> None:
    t = FakeTransport(http_error(403, "Resource not accessible by integration"))
    client, clock = make(t)
    with pytest.raises(AccessDeniedError, match="not accessible") as info:
        get(client)
    assert not isinstance(info.value, GitHubRateLimitError)
    assert clock.sleeps == [] and len(t.requests) == 1


def test_wait_longer_than_budget_fails_fast_with_clear_error() -> None:
    t = FakeTransport(
        http_error(
            403,
            "API rate limit exceeded",
            x_ratelimit_remaining="0",
            x_ratelimit_reset=str(int(NOW) + 3600),
        )
    )
    client, clock = make(t, RetryPolicy(max_total_wait_seconds=30))
    with pytest.raises(GitHubRateLimitError) as info:
        get(client)
    err = info.value
    assert err.kind == "primary" and err.attempts == 1 and clock.sleeps == []
    assert err.retry_after_seconds == pytest.approx(3601)
    assert "primary rate limit" in str(err)
    assert "GET /repos/o/r/issues/1/comments" in str(err)
    assert TOKEN not in str(err)
    assert isinstance(err, AccessDeniedError)


def test_attempts_are_bounded() -> None:
    t = FakeTransport(*[http_error(429, "limit", retry_after="1") for _ in range(10)])
    client, clock = make(t, RetryPolicy(max_attempts=3, max_total_wait_seconds=100))
    with pytest.raises(GitHubRateLimitError) as info:
        get(client)
    assert len(t.requests) == 3 and len(clock.sleeps) == 2
    assert info.value.attempts == 3
    assert info.value.waited_seconds == pytest.approx(2.0)


def test_total_wait_budget_is_bounded() -> None:
    t = FakeTransport(*[http_error(429, "limit", retry_after="4") for _ in range(10)])
    client, clock = make(t, RetryPolicy(max_attempts=10, max_total_wait_seconds=10))
    with pytest.raises(GitHubRateLimitError):
        get(client)
    assert sum(clock.sleeps) <= 10 and len(t.requests) == 3


def test_post_is_retried_after_a_rate_limit_rejection() -> None:
    t = FakeTransport(http_error(429, "limit", retry_after="1"), Response({"id": 9}))
    client, _ = make(t)
    assert post(client) == {"id": 9}
    assert len(t.requests) == 2 and t.requests[1].get_method() == "POST"


def test_post_is_never_retried_after_a_server_error_or_network_error() -> None:
    for failure in (http_error(502, "bad gateway"), urllib.error.URLError("timed out")):
        t = FakeTransport(failure, Response({"id": 1}))
        client, clock = make(t)
        with pytest.raises((AccessDeniedError, ValidationError)):
            post(client)
        assert len(t.requests) == 1 and clock.sleeps == []


def test_get_retries_server_errors_with_exponential_backoff() -> None:
    t = FakeTransport(
        http_error(503, "unavailable"), http_error(502, "gateway"), Response([])
    )
    client, clock = make(t)
    get(client)
    assert clock.sleeps == [1.0, 2.0]


def test_get_retries_network_errors_then_reports_them() -> None:
    t = FakeTransport(urllib.error.URLError("reset"), Response([]))
    client, clock = make(t)
    get(client)
    assert clock.sleeps == [1.0]
    t = FakeTransport(*[urllib.error.URLError("reset") for _ in range(10)])
    client, _ = make(t, RetryPolicy(max_attempts=2))
    with pytest.raises(ValidationError, match="reset"):
        get(client)


def test_other_client_errors_are_not_retried() -> None:
    for code in (401, 404, 422):
        t = FakeTransport(http_error(code, "nope"))
        client, _ = make(t)
        with pytest.raises(AccessDeniedError, match="nope"):
            get(client)
        assert len(t.requests) == 1


def test_retry_can_be_disabled() -> None:
    t = FakeTransport(http_error(429, "limit", retry_after="1"), Response([]))
    client, clock = make(t, RetryPolicy.disabled())
    with pytest.raises(GitHubRateLimitError):
        get(client)
    assert len(t.requests) == 1 and clock.sleeps == []


def test_classification_and_header_parsing() -> None:
    assert classify_rate_limit(403, headers(x_ratelimit_remaining="0"), "") == "primary"
    abuse = '{"message":"abuse detection mechanism"}'
    assert classify_rate_limit(403, headers(), abuse) == "secondary"
    assert classify_rate_limit(403, headers(retry_after="3"), "") == "secondary"
    assert (
        classify_rate_limit(403, headers(x_ratelimit_remaining="12"), "forbidden")
        is None
    )
    assert classify_rate_limit(500, headers(retry_after="3"), "") is None
    bad = headers(x_ratelimit_remaining="x", x_ratelimit_reset="-5", retry_after="nan")
    info = parse_rate_limit(bad)
    assert (
        info.remaining is None and info.reset_epoch is None and info.retry_after is None
    )
    assert parse_rate_limit(None).remaining is None
    assert parse_rate_limit({"X-RateLimit-Remaining": "7"}).remaining == 7


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
