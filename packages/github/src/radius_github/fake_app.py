"""In-memory GitHub REST API for the GitHub *App* client (tests and demos).

``FakeGitHubApp.opener`` replaces ``urllib.request.urlopen`` for
:class:`radius_github.GitHubAppClient`, so the real client (RS256 JWT signing
included) runs against it with no sockets. It models only what the pull-based
connect/sync/analyze flow and ``scripts/live_check.py`` read:

* ``GET /app`` (App JWT), ``GET /repos/{o}/{r}/installation`` (App JWT),
  ``POST /app/installations/{id}/access_tokens`` (App JWT; returns permissions);
* ``GET /repos/{o}/{r}``, ``GET /repos/{o}/{r}/pulls`` and ``.../pulls/{n}``
  with an installation token (``ghs_...``).

It is a test double: real GitHub behaviour that it does not reproduce (secondary
rate limits, SSO enforcement, renamed repositories) is only confirmed by a live
run.
"""

from __future__ import annotations

import io
import json
import secrets
import urllib.error
from typing import Any
from urllib.parse import unquote, urlsplit

DEFAULT_PERMISSIONS = {
    "metadata": "read",
    "contents": "read",
    "pull_requests": "write",
    "checks": "write",
}


class _Response(io.BytesIO):
    def __init__(self, payload: Any, headers: dict[str, str]) -> None:
        super().__init__(json.dumps(payload).encode())
        self.headers = headers

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeGitHubApp:
    """See the module docs. Mutate the public attributes to model failures."""

    def __init__(
        self,
        *,
        owner: str = "acme",
        repo: str = "widgets",
        app_id: str = "12345",
        installation_id: int = 9001,
        repository_id: int = 4242,
        public_key_pem: str | None = None,
        clone_url: str | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.app_id = app_id
        self.installation_id = installation_id
        self.repository_id = repository_id
        self.public_key_pem = public_key_pem
        self.clone_url = clone_url or f"https://github.com/{owner}/{repo}.git"
        self.default_branch = "main"
        self.private = True
        #: Permissions of the App installation and of tokens minted for it.
        self.permissions: dict[str, str] = dict(DEFAULT_PERMISSIONS)
        self.installed = True
        self.repository_accessible = True
        self.pulls: list[dict[str, Any]] = []
        #: ``{(METHOD, path): status}`` forced error responses.
        self.fail: dict[tuple[str, str], int] = {}
        self.server_date = "Tue, 03 Nov 2026 10:00:00 GMT"
        self.requests: list[tuple[str, str]] = []
        self.jwt_verified = 0
        self.tokens: set[str] = set()

    def add_pull(
        self,
        number: int,
        *,
        head_sha: str,
        title: str = "A change",
        body: str | None = "",
        draft: bool = False,
        state: str = "open",
        head_ref: str = "feature",
        base_ref: str = "main",
        author: str = "dev",
    ) -> dict[str, Any]:
        pull = {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "draft": draft,
            "merged": False,
            "merged_at": None,
            "user": {"login": author},
            "head": {"ref": head_ref, "sha": head_sha},
            "base": {"ref": base_ref, "sha": "0" * 40},
            "created_at": "2026-11-02T10:00:00Z",
        }
        self.pulls.append(pull)
        return pull

    # -- urllib adapter -------------------------------------------------------
    def opener(self, request: Any, timeout: float | None = None) -> _Response:  # noqa: ARG002
        body = json.loads(request.data) if request.data else None
        status, payload = self.handle(
            request.get_method(), request.full_url, dict(request.header_items()), body
        )
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "error",
                {"Date": self.server_date},  # type: ignore[arg-type]
                io.BytesIO(json.dumps(payload).encode()),
            )
        return _Response(payload, {"x-ratelimit-remaining": "4999", "Date": self.server_date})

    # -- router ---------------------------------------------------------------
    def handle(
        self, method: str, url: str, headers: dict[str, str], body: Any  # noqa: ARG002
    ) -> tuple[int, Any]:
        path = unquote(urlsplit(url).path)
        self.requests.append((method, path))
        forced = self.fail.get((method, path))
        if forced:
            return forced, {"message": f"forced {forced}"}
        auth = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        slug = f"/repos/{self.owner}/{self.repo}"

        if path == "/app" or path.endswith("/installation") or "/access_tokens" in path:
            if not self._jwt_ok(token):
                return 401, {"message": "A JSON web token could not be decoded"}
            if path == "/app":
                return 200, {
                    "id": 1,
                    "slug": "radius-demo",
                    "name": "Radius demo",
                    "permissions": dict(self.permissions),
                    "events": [],
                }
            if path == f"{slug}/installation":
                if not (self.installed and self.repository_accessible):
                    return 404, {"message": "Not Found"}
                return 200, {
                    "id": self.installation_id,
                    "permissions": dict(self.permissions),
                    "repository_selection": "selected",
                    "suspended_at": None,
                }
            if (
                method == "POST"
                and path == f"/app/installations/{self.installation_id}/access_tokens"
            ):
                if not self.installed:
                    return 404, {"message": "Not Found"}
                new_token = "ghs_" + secrets.token_hex(8)
                self.tokens.add(new_token)
                return 201, {
                    "token": new_token,
                    "expires_at": "2099-01-01T00:00:00Z",
                    "permissions": dict(self.permissions),
                    "repository_selection": "selected",
                }
            return 404, {"message": "Not Found"}

        if token not in self.tokens:
            return 401, {"message": "Bad credentials"}
        if not self.repository_accessible:
            return 404, {"message": "Not Found"}
        if method == "GET" and path == slug:
            return 200, {
                "id": self.repository_id,
                "name": self.repo,
                "full_name": f"{self.owner}/{self.repo}",
                "owner": {"login": self.owner},
                "private": self.private,
                "default_branch": self.default_branch,
                "clone_url": self.clone_url,
            }
        if method == "GET" and path == f"{slug}/pulls":
            return 200, [p for p in self.pulls if p["state"] == "open"]
        if method == "GET" and path.startswith(f"{slug}/pulls/"):
            number = path.rsplit("/", 1)[1]
            for pull in self.pulls:
                if str(pull["number"]) == number:
                    return 200, pull
        return 404, {"message": "Not Found"}

    def _jwt_ok(self, token: str) -> bool:
        import jwt

        try:
            if self.public_key_pem:
                claims = jwt.decode(
                    token,
                    self.public_key_pem,
                    algorithms=["RS256"],
                    options={"verify_iat": False},
                )
            else:
                claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return False
        if str(claims.get("iss")) != self.app_id:
            return False
        self.jwt_verified += 1
        return True
