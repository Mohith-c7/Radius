"""IN-02: the budgeted read-only REST client against the stateful fake."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from radius_github.fake_api import FakeGitHub
from radius_github.intent_rest import (
    CallBudget,
    EtagCache,
    GitHubRestReader,
    HttpResponse,
    TransportError,
    UrllibTransport,
)

TOKEN = "installation-token"


def reader(fake, cache: EtagCache | None = None) -> GitHubRestReader:
    return GitHubRestReader(transport=fake, cache=cache)


def get(r: GitHubRestReader, path: str, budget: CallBudget | None = None, **kw):
    return r.get_json(path, token=TOKEN, budget=budget or CallBudget(), **kw)


def test_ok_response_and_headers_sent() -> None:
    fake = FakeGitHub()
    fake.put("/repos/o/r/issues/1", {"number": 1})
    result = get(reader(fake), "/repos/o/r/issues/1")
    assert result.ok and result.data == {"number": 1} and result.status == 200
    call = fake.calls[0]
    assert call.headers["authorization"] == f"Bearer {TOKEN}"
    assert call.headers["accept"] == "application/vnd.github+json"
    assert call.headers["x-github-api-version"]
    assert call.headers["user-agent"]


@pytest.mark.parametrize(
    ("status", "kind", "reason"),
    [
        (404, "absent", "not_found"),
        (410, "absent", "gone"),
        (451, "absent", "blocked_by_policy"),
        (422, "absent", "unprocessable"),
        (403, "absent", "forbidden"),
        (500, "unavailable", "server_error"),
        (502, "unavailable", "server_error"),
        (503, "unavailable", "server_error"),
        (301, "unavailable", "redirected"),
        (418, "unavailable", "http_418"),
    ],
)
def test_status_classification(status: int, kind: str, reason: str) -> None:
    fake = FakeGitHub()
    fake.fail("/x", status, "boom")
    result = get(reader(fake), "/x")
    assert (result.kind, result.reason) == (kind, reason)
    assert not result.ok


def test_missing_permission_403_is_absent_not_rate_limited() -> None:
    fake = FakeGitHub()
    fake.deny_prefix("/repos/o/r/issues")
    budget = CallBudget()
    result = get(reader(fake), "/repos/o/r/issues/1", budget)
    assert (result.kind, result.reason) == ("absent", "forbidden")
    assert budget.tripped is None  # later calls still go out


@pytest.mark.parametrize("shape", ["primary", "secondary"])
def test_rate_limit_trips_the_budget(shape: str) -> None:
    fake = FakeGitHub()
    fake.put("/a", {"a": 1})
    fake.put("/b", {"b": 1})
    fake.rate_limit_after(1, shape)
    budget = CallBudget()
    r = reader(fake)
    assert get(r, "/a", budget).ok
    limited = get(r, "/b", budget)
    assert (limited.kind, limited.reason) == ("unavailable", "rate_limited")
    assert budget.tripped == "rate_limited"
    before = len(fake.calls)
    again = get(r, "/a", budget)
    assert again.reason == "rate_limited"
    assert len(fake.calls) == before  # no network once tripped


def test_403_with_rate_limit_message_only() -> None:
    fake = FakeGitHub()
    fake.fail("/x", 403, "You have triggered an abuse detection mechanism")
    assert get(reader(fake), "/x").reason == "rate_limited"
    fake2 = FakeGitHub()
    fake2.fail("/x", 403, "API rate limit exceeded")
    assert get(reader(fake2), "/x").reason == "rate_limited"


def test_bad_token_trips_budget_as_unauthorized() -> None:
    fake = FakeGitHub(tokens=("other",))
    fake.put("/a", {})
    budget = CallBudget()
    result = get(reader(fake), "/a", budget)
    assert (result.kind, result.reason) == ("unavailable", "unauthorized")
    assert budget.tripped == "unauthorized"


def test_call_budget_is_enforced() -> None:
    fake = FakeGitHub()
    fake.put("/a", {})
    budget = CallBudget(max_calls=2)
    r = reader(fake)
    assert get(r, "/a", budget).ok and get(r, "/a", budget).ok
    third = get(r, "/a", budget)
    assert third.reason == "budget_exhausted"
    assert len(fake.calls) == 2
    assert budget.exhausted


def test_deadline_is_enforced() -> None:
    now = [0.0]
    budget = CallBudget(max_calls=10, deadline_seconds=5, clock=lambda: now[0])
    fake = FakeGitHub()
    fake.put("/a", {})
    r = reader(fake)
    assert get(r, "/a", budget).ok
    now[0] = 6.0
    assert get(r, "/a", budget).reason == "deadline_exceeded"
    assert len(fake.calls) == 1


def test_timeout_passed_to_transport_is_bounded_by_remaining_deadline() -> None:
    seen: list[float] = []

    def transport(method, url, headers, timeout):
        seen.append(timeout)
        return HttpResponse(200, {}, b"{}")

    now = [0.0]
    budget = CallBudget(max_calls=5, deadline_seconds=3, clock=lambda: now[0])
    GitHubRestReader(transport=transport, timeout_seconds=10).get_json(
        "/a", token=TOKEN, budget=budget
    )
    assert seen == [3.0]


def test_etag_conditional_request_returns_cached_data_on_304() -> None:
    fake = FakeGitHub()
    fake.put("/repos/o/r/issues/1", {"number": 1, "title": "t"})
    cache = EtagCache()
    r = reader(fake, cache)
    first = get(r, "/repos/o/r/issues/1", scope="inst-1")
    second = get(r, "/repos/o/r/issues/1", scope="inst-1")
    assert first.data == second.data == {"number": 1, "title": "t"}
    assert not first.from_cache and second.from_cache
    assert [c.status for c in fake.calls] == [200, 304]
    assert "if-none-match" in fake.calls[1].headers


def test_changed_resource_is_refetched_after_an_etag_hit() -> None:
    fake = FakeGitHub()
    fake.put("/x", {"v": 1})
    r = reader(fake, EtagCache())
    get(r, "/x")
    fake.put("/x", {"v": 2})
    assert get(r, "/x").data == {"v": 2}
    assert [c.status for c in fake.calls] == [200, 200]


def test_etag_cache_is_scoped_per_installation_and_bounded() -> None:
    fake = FakeGitHub()
    fake.put("/x", {"v": 1})
    cache = EtagCache(max_entries=2)
    r = reader(fake, cache)
    get(r, "/x", scope="a")
    get(r, "/x", scope="b")
    assert [c.status for c in fake.calls] == [200, 200]  # b did not reuse a's etag
    get(r, "/x", scope="c")
    assert len(cache) == 2  # oldest evicted
    assert cache.get("a", "https://api.github.com/x") is None


def test_error_responses_are_not_cached() -> None:
    fake = FakeGitHub()
    cache = EtagCache()
    r = reader(fake, cache)
    assert get(r, "/missing").reason == "not_found"
    assert len(cache) == 0


def test_304_without_cache_entry_is_unavailable() -> None:
    def transport(method, url, headers, timeout):
        return HttpResponse(304, {}, b"")

    result = GitHubRestReader(transport=transport).get_json(
        "/a", token=TOKEN, budget=CallBudget()
    )
    assert result.reason == "invalid_response"


@pytest.mark.parametrize("reason", ["timeout", "network_error"])
def test_transport_errors_are_unavailable(reason: str) -> None:
    fake = FakeGitHub()
    fake.break_network(reason)
    result = get(reader(fake), "/a")
    assert (result.kind, result.reason) == ("unavailable", reason)
    fake.break_network(None)
    fake.put("/a", {})
    assert get(reader(fake), "/a").ok


def test_unexpected_transport_exception_does_not_escape() -> None:
    def transport(method, url, headers, timeout):
        raise RuntimeError("bug")

    result = GitHubRestReader(transport=transport).get_json(
        "/a", token=TOKEN, budget=CallBudget()
    )
    assert result.reason == "network_error"


def test_invalid_json_and_oversized_bodies_are_unavailable() -> None:
    def bad(method, url, headers, timeout):
        return HttpResponse(200, {}, b"{not json")

    assert (
        GitHubRestReader(transport=bad).get_json("/a", token=TOKEN, budget=CallBudget()).reason
        == "invalid_response"
    )

    def huge(method, url, headers, timeout):
        return HttpResponse(200, {}, b" " * (2 * 1024 * 1024 + 2))

    assert (
        GitHubRestReader(transport=huge).get_json("/a", token=TOKEN, budget=CallBudget()).reason
        == "response_too_large"
    )


def test_query_params_and_per_page_slicing() -> None:
    fake = FakeGitHub()
    fake.put("/list", [1, 2, 3, 4])
    result = get(reader(fake), "/list", params={"per_page": 2})
    assert result.data == [1, 2]
    assert fake.calls[0].query == {"per_page": "2"}


def test_non_get_is_rejected_by_the_fake() -> None:
    fake = FakeGitHub()
    assert fake("POST", "https://api.github.com/x", {"Authorization": "Bearer installation-token"}, 1).status == 405


# -- the real urllib transport, with urllib stubbed (no sockets) ---------------------


class _Resp:
    def __init__(self, status, body=b"{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, n=-1):
        return self._body[:n] if n >= 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _transport_with(monkeypatch, behavior) -> UrllibTransport:
    transport = UrllibTransport()
    monkeypatch.setattr(transport._opener, "open", behavior)  # noqa: SLF001
    return transport


def test_urllib_transport_success(monkeypatch) -> None:
    t = _transport_with(monkeypatch, lambda req, timeout: _Resp(200, b'{"a":1}', {"ETag": '"x"'}))
    response = t("GET", "https://api.github.com/x", {"A": "b"}, 3)
    assert response.status == 200 and response.headers["etag"] == '"x"'
    assert json.loads(response.body) == {"a": 1}


def test_urllib_transport_http_error_is_returned(monkeypatch) -> None:
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {"X-Y": "z"}, io.BytesIO(b'{"message":"Not Found"}'))

    response = _transport_with(monkeypatch, boom)("GET", "https://api.github.com/x", {}, 3)
    assert response.status == 404 and response.headers["x-y"] == "z"


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (TimeoutError(), "timeout"),
        (urllib.error.URLError(TimeoutError()), "timeout"),
        (urllib.error.URLError("dns"), "network_error"),
        (ConnectionResetError(), "network_error"),
    ],
)
def test_urllib_transport_network_errors(monkeypatch, exc, reason) -> None:
    def boom(req, timeout):
        raise exc

    with pytest.raises(TransportError) as info:
        _transport_with(monkeypatch, boom)("GET", "https://api.github.com/x", {}, 3)
    assert info.value.reason == reason


def test_urllib_transport_does_not_follow_redirects() -> None:
    handler = UrllibTransport()._opener.handlers  # noqa: SLF001
    redirect = [h for h in handler if h.__class__.__name__ == "_NoRedirect"]
    assert redirect and redirect[0].redirect_request(None) is None
