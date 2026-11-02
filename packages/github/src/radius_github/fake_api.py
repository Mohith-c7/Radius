"""A stateful in-memory GitHub REST API for tests (IN-02).

Implements :class:`radius_github.intent_rest.HttpTransport`, so
:class:`~radius_github.intent_rest.GitHubRestReader` runs against it exactly as it
would against ``api.github.com``, without sockets. It is faithful where ingestion
depends on behavior:

* ``Authorization: Bearer <token>`` is required; unknown tokens get 401;
* ``ETag`` is a hash of the body and changes only when the resource changes;
  ``If-None-Match`` with the current ETag returns 304 with an empty body;
* ``per_page`` slices list responses;
* 404 for missing resources, 403 "Resource not accessible by integration" for a
  denied prefix, 410 for a deleted issue, 5xx on request, and both rate-limit
  shapes (403 with ``x-ratelimit-remaining: 0`` and 429 with ``retry-after``);
* every request is recorded in :attr:`calls` so tests can assert the API-call budget.

State can change between calls (``put`` again, ``remove``, ``fail``), which is how
tests model a PR edit, a new commit or a revoked permission. It does not model
pagination links, GraphQL, or anything outside what ingestion reads. Real GitHub
behavior that is NOT reproduced here (secondary limits, redirects for renamed
repositories, response variations) is what the F-06 live run has to confirm.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from radius_github.intent_rest import HttpResponse, TransportError

API_HOST = "api.github.com"


@dataclass
class _Route:
    status: int
    data: Any
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    version: int = 1


@dataclass(frozen=True)
class RecordedCall:
    """One request the fake saw."""

    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    status: int


class FakeGitHub:
    """See the module docs."""

    def __init__(self, *, tokens: tuple[str, ...] = ("installation-token",)) -> None:
        self.tokens = set(tokens)
        self.calls: list[RecordedCall] = []
        self._routes: dict[str, list[_Route]] = {}
        self._denied: list[tuple[str, int, str, dict[str, str]]] = []
        self._rate_limit_after: int | None = None
        self._rate_limit_shape = "primary"
        self._network_error: str | None = None

    # -- arrange -------------------------------------------------------------
    def put(
        self,
        path: str,
        data: Any,
        *,
        params: Mapping[str, str] | None = None,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Create or replace the resource at ``path`` (and optional query match)."""
        wanted = dict(params or {})
        routes = self._routes.setdefault(path, [])
        for route in routes:
            if route.params == wanted:
                route.status, route.data = status, data
                route.headers = dict(headers or {})
                route.version += 1
                return
        routes.append(_Route(status, data, dict(headers or {}), wanted))

    def remove(self, path: str, *, params: Mapping[str, str] | None = None) -> None:
        """Delete the resource: later requests get 404."""
        wanted = dict(params or {})
        self._routes[path] = [
            r for r in self._routes.get(path, []) if r.params != wanted
        ]

    def fail(
        self,
        path: str,
        status: int,
        message: str = "error",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Make ``path`` (an exact path) answer ``status`` with a GitHub-style error body."""
        self._routes[path] = [
            _Route(
                status,
                {"message": message, "documentation_url": "https://docs.github.com/rest"},
                dict(headers or {}),
            )
        ]

    def deny_prefix(
        self, prefix: str, status: int = 403, message: str = "Resource not accessible by integration"
    ) -> None:
        """Deny every path under ``prefix`` (a missing App permission)."""
        self._denied.append((prefix, status, message, {}))

    def allow_prefix(self, prefix: str) -> None:
        """Undo :meth:`deny_prefix`."""
        self._denied = [d for d in self._denied if d[0] != prefix]

    def rate_limit_after(self, calls: int | None, shape: str = "primary") -> None:
        """Start answering rate-limited once ``calls`` requests were made."""
        self._rate_limit_after = calls
        self._rate_limit_shape = shape

    def break_network(self, reason: str | None = "network_error") -> None:
        """Raise :class:`TransportError` for every request (``None`` repairs it)."""
        self._network_error = reason

    # -- convenience builders (shapes copied from the REST docs) ------------------
    def put_pull(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        title: str,
        body: str | None,
        head_sha: str,
        user: str = "contributor-test",
        commits: int = 1,
    ) -> None:
        """Register ``GET /repos/{owner}/{repo}/pulls/{number}``."""
        self.put(
            f"/repos/{owner}/{repo}/pulls/{number}",
            {
                "url": f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
                "number": number,
                "state": "open",
                "title": title,
                "body": body,
                "user": {"login": user, "type": "User"},
                "head": {"ref": "feature/x", "sha": head_sha},
                "base": {"ref": "main", "sha": "0" * 40},
                "commits": commits,
                "author_association": "OWNER",
            },
        )

    def put_commits(
        self,
        owner: str,
        repo: str,
        number: int,
        commits: list[tuple[str, str, int]],
    ) -> None:
        """Register the PR commit list: ``[(sha, message, parent_count), ...]``."""
        self.put(
            f"/repos/{owner}/{repo}/pulls/{number}/commits",
            [
                {
                    "sha": sha,
                    "commit": {"message": message, "author": {"name": "A", "email": "a@example.invalid"}},
                    "parents": [{"sha": "p" * 40}] * parents,
                }
                for sha, message, parents in commits
            ],
        )

    def put_file(self, owner: str, repo: str, path: str, text: str, *, ref: str) -> None:
        """Register ``GET /repos/{owner}/{repo}/contents/{path}?ref=...``."""
        raw = text.encode("utf-8")
        encoded = base64.encodebytes(raw).decode("ascii")  # newline every 76 chars
        self.put(
            f"/repos/{owner}/{repo}/contents/{path}",
            {
                "type": "file",
                "encoding": "base64",
                "size": len(raw),
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "sha": hashlib.sha1(raw).hexdigest(),  # noqa: S324 - git blob id shape
                "content": encoded,
            },
            params={"ref": ref},
        )

    def put_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        title: str,
        body: str | None,
        comments: list[dict[str, Any]] | None = None,
        is_pull_request: bool = False,
        state: str = "open",
    ) -> None:
        """Register an issue and its comments."""
        issue: dict[str, Any] = {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "user": {"login": "reporter", "type": "User"},
            "comments": len(comments or []),
            "author_association": "NONE",
        }
        if is_pull_request:
            issue["pull_request"] = {"url": f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"}
        self.put(f"/repos/{owner}/{repo}/issues/{number}", issue)
        self.put(f"/repos/{owner}/{repo}/issues/{number}/comments", comments or [])

    # -- transport -------------------------------------------------------------
    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Serve one request."""
        del timeout
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        path = parts.path
        lowered = {k.lower(): v for k, v in headers.items()}
        if self._network_error:
            self.calls.append(RecordedCall(method, path, query, lowered, 0))
            raise TransportError(self._network_error)
        response = self._serve(method, path, query, lowered)
        self.calls.append(RecordedCall(method, path, query, lowered, response.status))
        return response

    def _serve(
        self, method: str, path: str, query: dict[str, str], headers: dict[str, str]
    ) -> HttpResponse:
        auth = headers.get("authorization", "")
        if method != "GET":
            return _error(405, "Method not allowed")
        if not auth.startswith("Bearer ") or auth[7:] not in self.tokens:
            return _error(401, "Bad credentials")
        if self._rate_limit_after is not None and len(self.calls) >= self._rate_limit_after:
            if self._rate_limit_shape == "secondary":
                return _error(429, "You have exceeded a secondary rate limit.", {"retry-after": "60"})
            return _error(
                403,
                "API rate limit exceeded for installation.",
                {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"},
            )
        for prefix, status, message, extra in self._denied:
            if path.startswith(prefix):
                return _error(status, message, extra)
        route = self._match(path, query)
        if route is None:
            return _error(404, "Not Found")
        if route.status != 200:
            return HttpResponse(
                route.status,
                {"content-type": "application/json", **route.headers},
                json.dumps(route.data).encode(),
            )
        data = route.data
        per_page = query.get("per_page")
        if isinstance(data, list) and per_page and per_page.isdigit():
            data = data[: int(per_page)]
        body = json.dumps(data).encode("utf-8")
        etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
        out = {"content-type": "application/json; charset=utf-8", "etag": etag, **route.headers}
        if headers.get("if-none-match") == etag:
            return HttpResponse(304, {"etag": etag}, b"")
        return HttpResponse(200, out, body)

    def _match(self, path: str, query: dict[str, str]) -> _Route | None:
        candidates = [
            r
            for r in self._routes.get(path, [])
            if all(query.get(k) == v for k, v in r.params.items())
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: len(r.params))

    # -- assert --------------------------------------------------------------
    def paths(self) -> list[str]:
        """Paths requested so far, in order."""
        return [c.path for c in self.calls]

    def count(self, pattern: str) -> int:
        """Number of requests whose path matches the regex ``pattern``."""
        return sum(1 for c in self.calls if re.search(pattern, c.path))


def _error(status: int, message: str, headers: Mapping[str, str] | None = None) -> HttpResponse:
    body = json.dumps({"message": message, "documentation_url": "https://docs.github.com/rest"})
    return HttpResponse(
        status, {"content-type": "application/json", **(headers or {})}, body.encode()
    )




# -- recorded-style scenario --------------------------------------------------------

#: ``packages/github/tests/fixtures/api`` (REST responses shaped like GitHub's).
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "api"
RECORDED_OWNER = "radius-sandbox-owner"
RECORDED_REPO = "radius-sandbox"
RECORDED_HEAD_SHA = "1" * 39 + "a"
RECORDED_TOKEN = "installation-token"


def load_fixture(name: str) -> Any:
    """Load a recorded REST response from :data:`FIXTURE_DIR`."""
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def install_recorded_scenario(fake: FakeGitHub) -> FakeGitHub:
    """Register PR 1, its commits, the spec file and issues 12 and 13 from fixtures.

    The pull request carries ``Fixes #12`` in its body and ``Fixes #13`` in a
    commit message; issue 12 has three comments (a maintainer, a drive-by user and
    a bot).
    """
    base = f"/repos/{RECORDED_OWNER}/{RECORDED_REPO}"
    fake.put(f"{base}/pulls/1", load_fixture("pull_1.json"))
    fake.put(f"{base}/pulls/1/commits", load_fixture("pull_1_commits.json"))
    fake.put(
        f"{base}/contents/.radius/intent.yml",
        load_fixture("contents_intent_yml.json"),
        params={"ref": RECORDED_HEAD_SHA},
    )
    fake.put(f"{base}/issues/12", load_fixture("issue_12.json"))
    fake.put(f"{base}/issues/12/comments", load_fixture("issue_12_comments.json"))
    fake.put(f"{base}/issues/13", load_fixture("issue_13.json"))
    fake.put(f"{base}/issues/13/comments", [])
    return fake


__all__ = [
    "API_HOST",
    "FIXTURE_DIR",
    "RECORDED_HEAD_SHA",
    "RECORDED_OWNER",
    "RECORDED_REPO",
    "RECORDED_TOKEN",
    "FakeGitHub",
    "RecordedCall",
    "install_recorded_scenario",
    "load_fixture",
]
