#!/usr/bin/env python
"""End-to-end smoke test of the real Radius services (no network, no real GitHub).

    docker compose up -d postgres
    DATABASE_URL=postgresql+psycopg://radius:radius@localhost:5432/radius \
        python scripts/smoke_e2e.py

What runs for real: Alembic migrations on PostgreSQL, the FastAPI app (all
middleware, auth, rate limiting, routes, ASGI in-process through Starlette's
``TestClient``), the SQL job queue, the worker runtime and its poll loop
(``run_loop``), the real ``LocalGitRepositoryClient`` (``git clone`` of a local
repository), intent ingestion, Verdict v2 Stage A/B, the Verdict v2 renderer and
publisher, and the real ``GitHubAppClient`` (RS256 JWT signing included).

What is faked: only the network edge. A stateful in-memory "GitHub"
(:class:`FakeGitHub`) answers the REST calls that ``GitHubAppClient`` and the
intent ``GitHubRestReader`` make, and the "repository" is a git repo built from
the ``benchmarks/fixtures/intent/01_correct_strong_tests`` fixture (gold mode: the
fixture's links are given as ``.radius/intent.yml`` hints, identical on the base
ref so they are trusted as ``base_spec``). The PR body has a "Summary" bullet and the
worker runs with ``RADIUS_INTENT_EXTRACTION_MODE=summary`` (DEC-032), so one inferred,
unconfirmed criterion blocks ``verified`` until the confirm stage (DEC-033) confirms
the criteria through the real API and the worker recomputes and republishes.

It creates a throw-away database (``radius_smoke_<random>``) next to the one in
``DATABASE_URL`` and drops it at the end. The webhook secret, the API-key pepper,
the legacy API key and the GitHub App RSA key are generated per run.

Exit code 0 only if every check passed. Not covered: real GitHub, a browser or the
dashboard, Docker image builds, the test sandbox (``WORKER_EXECUTE_TESTS`` stays
off; CI results arrive as an uploaded JUnit report, the supported default).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = "01_correct_strong_tests"
FIXTURE_DIR = ROOT / "benchmarks" / "fixtures" / "intent" / FIXTURE
OWNER, REPO = "smoke-org", "pricing-service"
INSTALLATION_ID = 424242
GITHUB_REPO_ID = 777001
# The pull-based stage uses its own repository, installation and organization:
# nothing about it is delivered by a webhook or preconfigured on the organization.
PULL_REPO = "pull-demo"
PULL_INSTALLATION_ID = 515151
PULL_GITHUB_REPO_ID = 777002
PR_NUMBER = 7
STEPS: list[str] = []


class SmokeFailure(AssertionError):
    """A smoke check failed."""


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)
    STEPS.append(message)
    print(f"  ok   {message}", flush=True)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def _pythonpath() -> list[str]:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(config["tool"]["pytest"]["ini_options"]["pythonpath"])


# --------------------------------------------------------------------- database


def _admin_engine(database_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise SystemExit("scripts/smoke_e2e.py needs a PostgreSQL DATABASE_URL")
    if "+" not in url.drivername:
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, isolation_level="AUTOCOMMIT"), url


def create_database(database_url: str) -> tuple[str, str]:
    """Create ``radius_smoke_<hex>``; return ``(database_url_for_it, name)``."""

    from sqlalchemy import text

    engine, url = _admin_engine(database_url)
    name = f"radius_smoke_{uuid.uuid4().hex[:12]}"
    try:
        with engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()
    return url.set(database=name).render_as_string(hide_password=False), name


def drop_database(database_url: str, name: str) -> None:
    from sqlalchemy import text

    engine, _ = _admin_engine(database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the result
        print(f"warning: could not drop {name}: {type(exc).__name__}", file=sys.stderr)
    finally:
        engine.dispose()


# ------------------------------------------------------------------- fixture repo


def _git(args: list[str], cwd: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Smoke",
        "GIT_AUTHOR_EMAIL": "smoke@example.invalid",
        "GIT_COMMITTER_NAME": "Smoke",
        "GIT_COMMITTER_EMAIL": "smoke@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    out = subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _replace_tree(source: Path, target: Path) -> None:
    for child in target.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for item in source.rglob("*"):
        if item.is_file() and "__pycache__" not in item.parts:
            dest = target / item.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, dest)


def intent_spec(expected: dict[str, Any]) -> str:
    """``.radius/intent.yml`` with the fixture's gold links as hints."""

    links = {link["criterion"]: link for link in expected["links"]}
    lines = ["version: 1", "criteria:"]
    for criterion in expected["criteria"]:
        link = links[criterion["id"]]
        lines += [
            f"  - id: {criterion['id']}",
            f'    text: "{criterion["text"]}"',
            "    paths:",
            f'      - "{link["symbol"].split("::", 1)[0]}"',
            "    tests:",
            *[f'      - "{t}"' for t in link["tests"]],
        ]
    return "\n".join(lines) + "\n"


def build_origin_repo(path: Path, spec: str) -> tuple[str, str]:
    """A git repo with ``main`` = fixture base and ``feature`` = fixture head."""

    path.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], path)
    _replace_tree(FIXTURE_DIR / "base", path)
    (path / ".radius").mkdir()
    (path / ".radius" / "intent.yml").write_text(spec, encoding="utf-8", newline="\n")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "base"], path)
    base_sha = _git(["rev-parse", "HEAD"], path)
    _git(["checkout", "-q", "-b", "feature"], path)
    _replace_tree(FIXTURE_DIR / "head", path)
    (path / ".radius").mkdir(exist_ok=True)
    (path / ".radius" / "intent.yml").write_text(spec, encoding="utf-8", newline="\n")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "Add apply_discount"], path)
    head_sha = _git(["rev-parse", "HEAD"], path)
    _git(["checkout", "-q", "main"], path)
    return base_sha, head_sha


def junit_from_outcomes(outcomes: dict[str, str]) -> bytes:
    """A JUnit XML report for ``{"tests/x.py::name": "passed"|"failed"|"skipped"}``."""

    cases = []
    for test_id, outcome in sorted(outcomes.items()):
        file, name = test_id.rsplit("::", 1)
        classname = file.removesuffix(".py").replace("/", ".")
        inner = {"failed": '<failure message="assert"/>', "skipped": "<skipped/>"}.get(outcome, "")
        cases.append(f'<testcase classname="{classname}" name="{name}">{inner}</testcase>')
    body = "".join(cases)
    return (
        f'<?xml version="1.0"?><testsuite name="smoke" tests="{len(cases)}">{body}</testsuite>'
    ).encode()


# ------------------------------------------------------------------- fake GitHub


class _Response(io.BytesIO):
    """Minimal ``urlopen`` response for ``GitHubAppClient``."""

    def __init__(self, payload: Any) -> None:
        super().__init__(json.dumps(payload).encode())
        self.headers: dict[str, str] = {"x-ratelimit-remaining": "4999"}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeGitHub:
    """Stateful in-memory GitHub REST API (the only fake in the smoke).

    ``opener`` is the ``urlopen`` replacement for ``GitHubAppClient``; ``transport``
    is the ``HttpTransport`` of the intent reader. Both go through :meth:`handle`.
    """

    def __init__(
        self,
        *,
        public_key_pem: str,
        head_sha: str,
        spec: str,
        owner: str = OWNER,
        repo: str = REPO,
        installation_id: int = INSTALLATION_ID,
        github_repo_id: int = GITHUB_REPO_ID,
        clone_url: str = "",
    ) -> None:
        self.owner, self.repo = owner, repo
        self.installation_id = installation_id
        self.github_repo_id = github_repo_id
        self.clone_url = clone_url
        #: Other repositories served by the same fake GitHub (same App, own installation).
        self.others: list[FakeGitHub] = []
        self.public_key_pem = public_key_pem
        self.head_sha = head_sha
        self.spec = spec
        self.pr_body = "Adds apply_discount to pricing."
        self.check_runs: list[dict[str, Any]] = []
        self.comments: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str]] = []
        self.unhandled: list[tuple[str, str]] = []
        self.jwt_verified = 0

    # -- adapters
    def opener(self, request: Any, timeout: float | None = None) -> _Response:  # noqa: ARG002
        body = json.loads(request.data) if request.data else None
        status, payload = self.handle(
            request.get_method(), request.full_url, dict(request.header_items()), body
        )
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "error", {}, io.BytesIO(json.dumps(payload).encode())  # type: ignore[arg-type]
            )
        return _Response(payload)

    def transport(self, method: str, url: str, headers: Any, timeout: float):  # noqa: ARG002
        from radius_github.intent_rest import HttpResponse

        status, payload = self.handle(method, url, dict(headers), None)
        return HttpResponse(
            status=status,
            headers={"content-type": "application/json", "x-ratelimit-remaining": "4999"},
            body=json.dumps(payload).encode(),
        )

    # -- router
    def handle(
        self, method: str, url: str, headers: dict[str, str], body: Any
    ) -> tuple[int, Any]:
        parts = urlsplit(url)
        path, query = unquote(parts.path), parse_qs(parts.query)
        for other in self.others:
            if other.serves(path):
                return other.handle(method, url, headers, body)
        self.requests.append((method, path))
        auth = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        slug = f"/repos/{self.owner}/{self.repo}"

        if method == "GET" and path == f"{slug}/installation":
            import jwt

            jwt.decode(token, self.public_key_pem, algorithms=["RS256"])
            self.jwt_verified += 1
            return 200, {"id": self.installation_id, "suspended_at": None}
        if method == "GET" and path == slug and token.startswith("ghs_"):
            return 200, {
                "id": self.github_repo_id, "name": self.repo, "private": True,
                "default_branch": "main", "clone_url": self.clone_url,
                "owner": {"login": self.owner},
            }
        if method == "POST" and path == f"/app/installations/{self.installation_id}/access_tokens":
            import jwt

            claims = jwt.decode(token, self.public_key_pem, algorithms=["RS256"])
            if not claims.get("iss"):
                return 401, {"message": "bad jwt"}
            self.jwt_verified += 1
            return 201, {"token": "ghs_" + secrets.token_hex(8), "expires_at": "2099-01-01T00:00:00Z"}
        if not token.startswith("ghs_"):
            return 401, {"message": "Bad credentials"}

        if method == "GET" and path == f"{slug}/pulls":
            return 200, [self._pull()]
        if method == "GET" and path == f"{slug}/pulls/{PR_NUMBER}":
            return 200, self._pull()
        if method == "GET" and path == f"{slug}/pulls/{PR_NUMBER}/commits":
            return 200, [
                {
                    "sha": self.head_sha,
                    "parents": [{"sha": "0" * 40}],
                    "commit": {"message": "Add apply_discount"},
                }
            ]
        if method == "GET" and path == f"{slug}/contents/.radius/intent.yml":
            data = self.spec.encode()
            return 200, {
                "type": "file",
                "encoding": "base64",
                "size": len(data),
                "content": base64.b64encode(data).decode(),
            }
        if method == "POST" and path == f"{slug}/check-runs":
            run = {**body, "id": len(self.check_runs) + 1, "started_at": f"2026-11-02T10:00:{len(self.check_runs):02d}Z"}
            self.check_runs.append(run)
            return 201, run
        if method == "PATCH" and path.startswith(f"{slug}/check-runs/"):
            run = self._by_id(self.check_runs, path.rsplit("/", 1)[1])
            if run is None:
                return 404, {"message": "Not Found"}
            run.update(body)
            return 200, run
        if method == "GET" and re.fullmatch(rf"{re.escape(slug)}/commits/[^/]+/check-runs", path):
            wanted = query.get("check_name", [None])[0]
            ref = path.split("/")[-2]
            runs = [
                r for r in self.check_runs
                if r.get("head_sha") == ref and (wanted is None or r.get("name") == wanted)
            ]
            return 200, {"total_count": len(runs), "check_runs": runs}
        if method == "GET" and path == f"{slug}/issues/{PR_NUMBER}/comments":
            return 200, self.comments
        if method == "POST" and path == f"{slug}/issues/{PR_NUMBER}/comments":
            comment = {
                "id": 9000 + len(self.comments),
                "body": body["body"],
                "user": {"login": "radius[bot]", "type": "Bot"},
            }
            self.comments.append(comment)
            return 201, comment
        if method == "PATCH" and path.startswith(f"{slug}/issues/comments/"):
            comment = self._by_id(self.comments, path.rsplit("/", 1)[1])
            if comment is None:
                return 404, {"message": "Not Found"}
            comment["body"] = body["body"]
            return 200, comment
        self.unhandled.append((method, path))
        return 404, {"message": "Not Found"}

    def serves(self, path: str) -> bool:
        """Whether ``path`` belongs to this repository (or its installation token)."""

        slug = f"/repos/{self.owner}/{self.repo}"
        return (
            path == slug
            or path.startswith(slug + "/")
            or path == f"/app/installations/{self.installation_id}/access_tokens"
        )

    @staticmethod
    def _by_id(items: list[dict[str, Any]], raw_id: str) -> dict[str, Any] | None:
        return next((i for i in items if str(i["id"]) == raw_id), None)

    def _pull(self) -> dict[str, Any]:
        return {
            "number": PR_NUMBER,
            "title": "Add apply_discount",
            "body": self.pr_body,
            "state": "open",
            "head": {"sha": self.head_sha, "ref": "feature"},
            "base": {"ref": "main", "sha": "0" * 40},
            "draft": False,
            "merged": False,
            "merged_at": None,
            "user": {"login": "dev"},
            "created_at": "2026-11-02T10:00:00Z",
        }


# ------------------------------------------------------------------------- smoke


class Smoke:
    def __init__(self, workdir: Path, database_url: str) -> None:
        self.workdir = workdir
        self.database_url = database_url
        self.webhook_secret = secrets.token_hex(24)
        self.pepper = secrets.token_hex(24)
        self.legacy_key = "legacy-" + secrets.token_hex(16)
        # RADIUS_SMOKE_ORG_ID lets a developer reuse the local-dev organization when inspecting a kept database.
        self.org_id = uuid.UUID(os.environ["RADIUS_SMOKE_ORG_ID"]) if os.environ.get("RADIUS_SMOKE_ORG_ID") else uuid.uuid4()
        self.other_org_id = uuid.uuid4()
        self.pull_org_id = uuid.uuid4()
        self.pull_key = "pull-" + secrets.token_hex(16)
        self.expected = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
        self.headers: dict[str, str] = {}
        self.client: Any = None
        self.runtime: Any = None
        self.github: FakeGitHub
        self.base_sha = self.head_sha = ""
        self.analysis_id = ""
        self.webhook_calls = 0
        self.blocked_payload: dict[str, Any] = {}
        self.blocked_comment = ""

    # -- helpers
    def api(self, method: str, path: str, **kwargs: Any):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.request(method, f"/api/v1{path}", headers=headers, **kwargs)

    def webhook(self, payload: dict[str, Any], *, delivery: str, event: str = "pull_request",
                secret: str | None = None, sign: bool = True):
        self.webhook_calls += 1
        body = json.dumps(payload).encode()
        headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery,
                   "Content-Type": "application/json"}
        if sign:
            digest = hmac.new((secret or self.webhook_secret).encode(), body, hashlib.sha256)
            headers["X-Hub-Signature-256"] = "sha256=" + digest.hexdigest()
        return self.client.post("/api/v1/webhooks/github", content=body, headers=headers)

    def run_worker(self) -> None:
        """The real poll loop; returns after it has been idle for three cycles."""

        self.runtime.run_loop(poll_interval_seconds=0.05, stop_after_idle_cycles=3)

    def pr_payload(self) -> dict[str, Any]:
        return {
            "action": "opened",
            "installation": {"id": INSTALLATION_ID},
            "repository": {
                "id": GITHUB_REPO_ID, "name": REPO, "private": True,
                "default_branch": "main", "clone_url": str(self.origin),
                "owner": {"login": OWNER},
            },
            "pull_request": {
                "number": PR_NUMBER, "title": "Add apply_discount",
                "body": self.github.pr_body, "state": "open", "draft": False,
                "merged": False, "user": {"login": "dev"},
                "head": {"ref": "feature", "sha": self.head_sha},
                "base": {"ref": "main", "sha": self.base_sha},
                "created_at": "2026-11-02T10:00:00Z", "merged_at": None,
            },
        }

    # -- stages
    def setup(self) -> None:
        section("setup: migrations, repository, services")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        spec = intent_spec(self.expected)
        self.origin = self.workdir / "origin"
        self.base_sha, self.head_sha = build_origin_repo(self.origin, spec)
        self.github = FakeGitHub(public_key_pem=public_pem, head_sha=self.head_sha, spec=spec)
        self.github.pr_body = (
            "Adds apply_discount to pricing.\n\n## Summary\n"
            "- Rejects a percent outside 0..100 inclusive with a ValueError\n"
        )

        env = {
            "DATABASE_URL": self.database_url,
            "STORAGE_BACKEND": "sql",
            "GITHUB_WEBHOOK_SECRET": self.webhook_secret,
            "API_KEYS": f"{self.org_id}:{self.legacy_key},{self.pull_org_id}:{self.pull_key}",
            "RADIUS_API_KEY_PEPPER": self.pepper,
            "RADIUS_FEATURE_VERDICT_V2": "on",
            "RADIUS_FEATURE_INTENT_INGESTION": "true",
            "RADIUS_INTENT_EXTRACTION_MODE": "summary",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_PRIVATE_KEY": private_pem,
            "GITHUB_PUBLISH_RESULTS": "true",
            "DASHBOARD_BASE_URL": "https://dashboard.smoke.invalid",
            "REPOSITORY_CACHE_DIR": str(self.workdir / "cache"),
            "SESSION_SECRET": secrets.token_hex(32),
            "RADIUS_LOG_LEVEL": "WARNING",
        }
        # Start from a clean slate: a developer's RADIUS_/WORKER_/GITHUB_ variables
        # (or the pytest wrapper's insecure-dev defaults) must not change the run.
        for name in [n for n in os.environ if n.startswith(("RADIUS_", "WORKER_", "GITHUB_"))]:
            del os.environ[name]
        os.environ.update(env)

        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        check(True, "alembic upgrade head applied to a fresh PostgreSQL database")

        from radius_shared.database import models as db_models
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(self.database_url)
        with sessionmaker(bind=engine)() as session:
            session.add_all([
                db_models.Organization(id=self.org_id, name="Smoke Org",
                                       github_installation_id=INSTALLATION_ID),
                db_models.Organization(id=self.other_org_id, name="Other Org",
                                       github_installation_id=INSTALLATION_ID + 1),
                # No installation id: the pull stage must discover and store it.
                db_models.Organization(id=self.pull_org_id, name="Pull Org"),
            ])
            session.commit()
        engine.dispose()

        from fastapi.testclient import TestClient
        from radius_api.main import create_app

        self.app = create_app()
        self.client = TestClient(self.app)
        self.pull_github = FakeGitHub(
            public_key_pem=public_pem, head_sha=self.head_sha, spec=spec,
            repo=PULL_REPO, installation_id=PULL_INSTALLATION_ID,
            github_repo_id=PULL_GITHUB_REPO_ID, clone_url=str(self.origin),
        )
        self.pull_github.pr_body = self.github.pr_body
        self.github.others.append(self.pull_github)
        self.client.__enter__()  # runs the app lifespan

        from radius_github import GitHubAppClient
        from radius_worker.config import WorkerSettings
        from radius_worker.runner import _github_settings, create_sql_worker_runtime

        settings = WorkerSettings()
        check(settings.verdict_v2_mode.value == "on", "worker sees RADIUS_FEATURE_VERDICT_V2=on")
        self.runtime = create_sql_worker_runtime(settings)
        self.runtime.github_client = GitHubAppClient(
            _github_settings(settings), opener=self.github.opener, sleep=lambda _s: None
        )
        self.runtime.intent_transport = self.github.transport
        # The API's pull-based routes talk to the same fake GitHub through the real
        # GitHubAppClient (the only override: its network opener).
        from radius_api.dependencies import get_github_client

        api_github = GitHubAppClient(
            _github_settings(settings), opener=self.github.opener, sleep=lambda _s: None
        )
        self.app.dependency_overrides[get_github_client] = lambda: api_github
        check(self.runtime.verdict_v2_recomputer is not None, "worker wired the Stage B recomputer")

    def health_and_auth(self) -> None:
        section("health, readiness, auth, rate limits")
        r = self.client.get("/api/v1/health")
        check(r.status_code == 200 and r.json()["data"]["status"] == "ok", "GET /health is ok")
        check(r.json()["data"]["storage"] == "sql", "API runs on SQL storage")
        r = self.client.get("/api/v1/ready")
        check(r.status_code == 200 and r.json()["data"]["status"] == "ok",
              "GET /ready is ok (database and job queue reachable)")
        check(r.headers.get("x-content-type-options") == "nosniff", "security headers are set")

        probe = f"/api/v1/analyses/{uuid.uuid4()}"
        r = self.client.get(probe)
        check(r.status_code in (401, 403), f"request without credentials is refused ({r.status_code})")
        r = self.client.get(probe, headers={"X-Radius-Organization-Id": str(self.org_id)})
        check(r.status_code in (401, 403), f"request without an API key is refused ({r.status_code})")
        r = self.client.get(probe, headers={"X-Radius-Organization-Id": str(self.org_id),
                                            "X-Radius-API-Key": "wrong-" + secrets.token_hex(8)})
        check(r.status_code in (401, 403), f"request with a wrong API key is refused ({r.status_code})")
        r = self.client.get(probe, headers={"X-Radius-Organization-Id": str(self.other_org_id),
                                            "X-Radius-API-Key": self.legacy_key})
        check(r.status_code in (401, 403), f"legacy key of another organization is refused ({r.status_code})")

        legacy = {"X-Radius-Organization-Id": str(self.org_id), "X-Radius-API-Key": self.legacy_key}
        r = self.client.get(probe, headers=legacy)
        check(r.status_code == 404, "legacy key authenticates (unknown analysis is 404)")

        r = self.client.post("/api/v1/api-keys", headers=legacy,
                             json={"name": "smoke-write", "scopes": ["write"]})
        check(r.status_code == 201, "managed API key created via the admin API")
        write_token = r.json()["data"]["token"]
        r = self.client.post("/api/v1/api-keys", headers=legacy,
                             json={"name": "smoke-read", "scopes": ["read"]})
        read_token = r.json()["data"]["token"]
        self.read_headers = {"X-Radius-Organization-Id": str(self.org_id), "X-Radius-API-Key": read_token}
        self.headers = {"X-Radius-Organization-Id": str(self.org_id), "X-Radius-API-Key": write_token}
        r = self.api("GET", f"/analyses/{uuid.uuid4()}")
        check(r.status_code == 404, "managed write key authenticates")
        check("RateLimit-Limit" in r.headers and "RateLimit-Remaining" in r.headers
              and "RateLimit-Policy" in r.headers,
              "authenticated responses carry rate-limit headers (RateLimit-Limit/-Remaining/-Policy)")
        r = self.api("POST", "/api-keys", json={"name": "x", "scopes": ["read"]})
        check(r.status_code in (401, 403), f"write key cannot use the admin API ({r.status_code})")

    def webhook_stage(self) -> None:
        section("webhook -> analysis")
        payload = self.pr_payload()
        r = self.webhook(payload, delivery="smoke-bad-sig", secret="not-the-secret")
        check(r.status_code in (401, 403), f"webhook with an invalid signature is rejected ({r.status_code})")
        r = self.webhook(payload, delivery="smoke-no-sig", sign=False)
        check(r.status_code in (401, 403), f"webhook without a signature is rejected ({r.status_code})")
        r = self.webhook({"zen": "smoke"}, delivery="smoke-ping", event="ping")
        check(r.status_code == 202, "signed ping is accepted")

        r = self.webhook(payload, delivery="smoke-delivery-1")
        check(r.status_code == 202, f"signed pull_request webhook is accepted (got {r.status_code}: {r.text[:200]})")
        data = r.json()["data"]
        self.analysis_id = data["analysisId"]
        check(bool(self.analysis_id) and not data.get("ignored"), "webhook created an analysis")
        replay = self.webhook(payload, delivery="smoke-delivery-1")
        check(replay.status_code == 202 and replay.json() == r.json(),
              "replaying the same delivery is idempotent (same analysis)")

        r = self.api("GET", f"/analyses/{self.analysis_id}")
        check(r.status_code == 200, "GET /analyses/{id} works with the managed key")
        check(r.json()["data"]["status"] == "pending", "analysis is pending before the worker runs")
        r = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2")
        check(r.status_code == 404 and r.json().get("meta", {}).get("reason") == "not_computed",
              "verdict-v2 is 404 not_computed before the worker ran")

    def worker_stage(self) -> None:
        section("worker loop -> verdict v2 -> GitHub")
        started = time.monotonic()
        self.run_worker()
        elapsed = time.monotonic() - started
        r = self.api("GET", f"/analyses/{self.analysis_id}")
        status = r.json()["data"]["status"]
        check(status == "completed", f"analysis completed by the worker in {elapsed:.1f}s (status={status})")
        check(self.github.jwt_verified >= 1, "worker authenticated to GitHub with a verifiable RS256 JWT")
        check(not self.github.unhandled, f"no unexpected GitHub API calls {self.github.unhandled}")

        r = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2")
        check(r.status_code == 200, f"verdict-v2 endpoint returns 200 (got {r.status_code}: {r.text[:200]})")
        payload = r.json()["data"]
        self.first_payload = payload
        check(payload["verdict"] == "insufficient_evidence",
              f"before CI results the verdict is insufficient_evidence (got {payload['verdict']})")
        check(r.headers.get("etag"), "verdict-v2 carries an ETag")
        r304 = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2",
                        headers={"If-None-Match": r.headers["etag"]})
        check(r304.status_code == 304, "If-None-Match yields 304")
        r = self.client.get(f"/api/v1/analyses/{self.analysis_id}/verdict-v2", headers=self.read_headers)
        check(r.status_code == 200, "read-only key can read the verdict")
        r = self.client.get(
            f"/api/v1/analyses/{self.analysis_id}/verdict-v2",
            headers={"X-Radius-Organization-Id": str(self.other_org_id),
                     "X-Radius-API-Key": "nope"},
        )
        check(r.status_code in (401, 403), "another organization cannot read the verdict")

        r = self.api("GET", f"/analyses/{self.analysis_id}/confidence")
        check(r.status_code == 200, "v1 confidence report is still available next to v2")

        self.assert_published(expected_verdict_label="insufficient", expect_rev=1)

    def assert_published(
        self,
        *,
        expected_verdict_label: str,
        expect_rev: int,
        github: FakeGitHub | None = None,
        analysis_id: str | None = None,
    ) -> None:
        from radius_github.verdict_v2.markdown import (
            DISCLAIMER,
            V2_MARKER_PREFIX,
            parse_v2_marker,
        )

        github = github or self.github
        analysis_id = analysis_id or self.analysis_id
        check(len(github.check_runs) == 1, "exactly one Check Run exists")
        run = github.check_runs[0]
        check(run["status"] == "completed" and run["head_sha"] == self.head_sha,
              "Check Run is completed on the PR head commit")
        check("v2 alpha" in run["output"]["title"], "Check Run title is the v2 alpha title")
        check(DISCLAIMER in run["output"]["summary"], "Check Run summary has the alpha disclaimer")
        check(len(github.comments) == 1, "exactly one PR comment exists")
        body = github.comments[0]["body"]
        check(DISCLAIMER in body, "PR comment has the alpha disclaimer")
        check(V2_MARKER_PREFIX in body, "PR comment carries the v2 marker")
        marker = parse_v2_marker(body)
        check(marker is not None and marker[0] == expect_rev,
              f"v2 marker revision is {expect_rev} (got {marker})")
        check(expected_verdict_label in body.lower(), f"PR comment shows the '{expected_verdict_label}' verdict")
        check(f"https://dashboard.smoke.invalid/analyses/{analysis_id}" in json.dumps(run),
              "Check Run links to the dashboard analysis page")

    def ci_stage(self) -> None:
        section("CI results -> republish")
        outcomes = self.expected["test_outcomes"]["head"]
        report = junit_from_outcomes(outcomes)
        path = f"/analyses/{self.analysis_id}/tests/results"

        r = self.api("POST", path, params={"commit_sha": "f" * 40}, content=report)
        check(r.status_code == 409, f"CI results for another commit are refused (409, got {r.status_code})")
        r = self.client.post(f"/api/v1{path}", params={"commit_sha": self.head_sha},
                             content=report, headers=self.read_headers)
        check(r.status_code in (401, 403), f"read-only key cannot upload CI results ({r.status_code})")
        r = self.api("POST", path, params={"commit_sha": self.head_sha}, content=b"not xml")
        check(r.status_code == 422, f"malformed report is refused (422, got {r.status_code})")

        r = self.api("POST", path, params={"commit_sha": self.head_sha}, content=report)
        check(r.status_code == 200, f"CI results upload accepted (got {r.status_code}: {r.text[:200]})")

        self.run_worker()
        r = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2")
        payload = r.json()["data"]
        if os.environ.get("SMOKE_DEBUG"):
            print(json.dumps(payload, indent=1)[:6000])
        check(payload["verdict"] == "insufficient_evidence",
              "after CI results the verdict is still insufficient_evidence: an inferred "
              f"criterion is unconfirmed (got {payload['verdict']})")
        check(payload["justification"]["decided_by"] == "R2d",
              f"decided by R2d (incomplete analysis: unconfirmed_inferred_intent), got {payload['justification']['decided_by']}")
        check(any("unconfirmed" in c["flags"] for c in payload["criteria"]),
              "criteria carry the 'unconfirmed' flag")
        check(payload["revision"] > self.first_payload["revision"],
              f"a new verdict revision was stored ({self.first_payload['revision']} -> {payload['revision']})")
        check(len(self.github.comments) == 1, "republish updated the PR comment in place (still one comment)")
        check(len(self.github.check_runs) == 1, "republish updated the Check Run in place (still one)")
        self.assert_published(expected_verdict_label="insufficient", expect_rev=payload["revision"])
        self.blocked_payload = payload
        self.blocked_comment = self.github.comments[0]["body"]
        writes_before = len(self.github.requests)
        self.run_worker()
        check(len(self.github.requests) == writes_before, "an idle worker makes no GitHub calls")

    def wait_for_revision(self, above: int, *, timeout_s: float = 90.0) -> dict[str, Any]:
        """Run the real worker loop until the stored revision is above ``above`` and no
        refresh is queued (the API debounces intent changes by a few seconds)."""

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.run_worker()
            r = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2")
            body = r.json()
            if (r.status_code == 200 and body["data"]["revision"] > above
                    and not body.get("meta", {}).get("refresh_pending")):
                return body["data"]
            time.sleep(0.5)
        raise SmokeFailure(f"no verdict revision above {above} appeared within {timeout_s:.0f}s")

    def confirm_stage(self) -> None:
        section("confirm criteria in the intent panel -> recompute -> republish in place")
        base = f"/analyses/{self.analysis_id}"
        before = self.blocked_payload
        r = self.api("GET", f"{base}/intent")
        criteria = r.json()["data"]["criteria"]
        check(len(criteria) >= 2 and {c["state"] for c in criteria} == {"proposed"},
              f"the intent panel lists {len(criteria)} proposed criteria")

        # not authenticated / wrong scope: no state change, no recompute request
        first = criteria[0]["id"]
        url = f"/api/v1{base}/intent/criteria/{first}"
        r = self.client.patch(url, json={"action": "confirm"})
        check(r.status_code in (401, 403), f"confirm without credentials is refused ({r.status_code})")
        r = self.client.patch(url, json={"action": "confirm"}, headers=self.read_headers)
        check(r.status_code == 403, f"confirm with a read-only key is refused ({r.status_code})")
        r = self.client.patch(url, json={"action": "confirm"}, headers={
            "X-Radius-Organization-Id": str(self.other_org_id), "X-Radius-API-Key": self.legacy_key})
        check(r.status_code in (401, 403), f"confirm with another organization's key is refused ({r.status_code})")
        r = self.api("PATCH", f"{base}/intent/criteria/{first}",
                     json={"action": "confirm", "provenance": "human_confirmed"})
        check(r.status_code == 422, f"a request body cannot carry a provenance ({r.status_code})")
        states = {c["state"] for c in self.api("GET", f"{base}/intent").json()["data"]["criteria"]}
        check(states == {"proposed"}, "refused calls changed no criterion state")
        r = self.api("GET", f"{base}/verdict-v2")
        check("refresh_pending" not in r.json().get("meta", {}),
              "refused calls enqueued no recompute (verdict not marked stale)")
        writes = len(self.github.requests)
        self.run_worker()
        check(len(self.github.requests) == writes, "the worker has nothing to do after refused calls")

        # confirming only some criteria must not lift the block (all summary-mode ones are needed)
        inferred = [c for c in criteria if "summary" in json.dumps(c.get("origin", {}))]
        check(len(inferred) >= 1, f"{len(inferred)} inferred (summary-mode) criterion listed")
        others = [c for c in criteria if c not in inferred]
        for criterion in others:
            r = self.api("PATCH", f"{base}/intent/criteria/{criterion['id']}", json={"action": "confirm"})
            check(r.status_code == 200, f"spec criterion {criterion['id'][:8]} confirmed through the API")
        mid = self.wait_for_revision(before["revision"])
        check(mid["verdict"] == "insufficient_evidence" and mid["justification"]["decided_by"] == "R2d",
              "with an inferred criterion still unconfirmed the block stays (R2d)")

        # the inferred criterion: confirmed twice in quick succession (second is refused)
        for criterion in inferred:
            r = self.api("PATCH", f"{base}/intent/criteria/{criterion['id']}", json={"action": "confirm"})
            check(r.status_code == 200 and r.json()["data"]["criterion"]["state"] == "confirmed",
                  f"inferred criterion {criterion['id'][:8]} confirmed through the API")
        r = self.api("PATCH", f"{base}/intent/criteria/{inferred[0]['id']}", json={"action": "confirm"})
        check(r.status_code == 409, f"confirming an already confirmed criterion is refused ({r.status_code})")
        r = self.api("GET", f"{base}/verdict-v2")
        meta = r.json().get("meta", {})
        check(meta.get("refresh_pending") is True and meta.get("refresh_reason") == "intent_changed",
              f"until the worker ran, the stored verdict is marked stale ({meta})")
        check(r.json()["data"]["revision"] == mid["revision"],
              "the stored revision has not changed yet (stale, as marked)")

        payload = self.wait_for_revision(mid["revision"])
        check(payload["verdict"] == "verified" and payload["justification"]["decided_by"] == "R4",
              "the unconfirmed_inferred_intent block is lifted: the verdict is verified again "
              f"(got {payload['verdict']} by {payload['justification']['decided_by']})")
        check(not any("unconfirmed" in c["flags"] for c in payload["criteria"]),
              "no criterion carries the 'unconfirmed' flag any more")
        check({c["provenance"] for c in payload["criteria"]} == {"human_confirmed"},
              "all criteria are now human_confirmed")
        check(payload["revision"] == mid["revision"] + 1,
              f"exactly one new revision was stored ({mid['revision']} -> {payload['revision']})")
        check(len(self.github.comments) == 1 and len(self.github.check_runs) == 1,
              "the PR comment and Check Run were edited in place (still one each)")
        check(self.github.comments[0]["body"] != self.blocked_comment,
              "the PR comment text changed after the confirm")
        self.assert_published(expected_verdict_label="supported", expect_rev=payload["revision"])
        r = self.api("GET", f"{base}/verdict-v2")
        check("refresh_pending" not in r.json().get("meta", {}), "the stale marker is gone")
        writes_before = len(self.github.requests)
        self.run_worker()
        check(len(self.github.requests) == writes_before, "an idle worker makes no GitHub calls")

    def regression_stage(self) -> None:
        section("idempotency and a failing CI report")
        path = f"/analyses/{self.analysis_id}/tests/results"
        outcomes = dict(self.expected["test_outcomes"]["head"])
        before = self.github.comments[0]["body"]
        r = self.api("POST", path, params={"commit_sha": self.head_sha}, content=junit_from_outcomes(outcomes))
        check(r.status_code == 200, "replayed identical CI report is accepted")
        self.run_worker()
        check(self.github.comments[0]["body"] == before, "identical evidence leaves the PR comment unchanged")

        # A later CI shard reports a failing linked test: failure is sticky and must
        # take the verdict away from "verified" and reach the PR comment.
        failing = {k: v for k, v in outcomes.items() if "rounds_to_cents" in k}
        failing = {k: "failed" for k in failing}
        r = self.api("POST", path, params={"commit_sha": self.head_sha}, content=junit_from_outcomes(failing))
        check(r.status_code == 200, "a second CI report with a failing test is accepted")
        self.run_worker()
        r = self.api("GET", f"/analyses/{self.analysis_id}/verdict-v2")
        verdict = r.json()["data"]["verdict"]
        check(verdict != "verified", f"a failing linked test removes 'verified' (verdict now {verdict})")
        check(len(self.github.comments) == 1 and len(self.github.check_runs) == 1,
              "the failure update edited the existing comment and Check Run in place")
        check(self.github.comments[0]["body"] != before, "the PR comment text changed with the new evidence")
        run = self.github.check_runs[0]
        check(run["conclusion"] != "success", f"Check Run conclusion is not success ({run['conclusion']})")

    def pull_stage(self) -> None:
        section("pull-based GitHub (no webhook): connect -> sync -> analyze -> worker -> publish")
        from radius_shared.database import models as db_models
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        gh = self.pull_github
        headers = {"X-Radius-Organization-Id": str(self.pull_org_id),
                   "X-Radius-API-Key": self.pull_key}

        def api(method: str, path: str, **kwargs: Any):
            return self.client.request(method, f"/api/v1{path}", headers=headers, **kwargs)

        def stored_installation() -> int | None:
            engine = create_engine(self.database_url)
            try:
                with sessionmaker(bind=engine)() as session:
                    return session.get(db_models.Organization, self.pull_org_id).github_installation_id
            finally:
                engine.dispose()

        webhook_calls_before = self.webhook_calls
        check(stored_installation() is None, "the organization starts with no GitHub installation id")
        check(not os.environ.get("GITHUB_INSTALLATION_ID"), "no GITHUB_INSTALLATION_ID is configured")

        r = api("POST", "/repositories/connect-github", json={"repository": "not a repo"})
        check(r.status_code == 422, f"a malformed repository name is refused ({r.status_code})")
        r = api("POST", "/repositories/connect-github", json={"repository": f"{OWNER}/{PULL_REPO}"})
        check(r.status_code == 201, f"connect by owner/name works (got {r.status_code}: {r.text[:200]})")
        repo = r.json()["data"]
        repository_id = repo["id"]
        check(repo["full_name"] == f"{OWNER}/{PULL_REPO}" and repo["default_branch"] == "main",
              "repository metadata (name, default branch) came from GitHub")
        check(r.json()["meta"]["installationId"] == PULL_INSTALLATION_ID,
              "the installation was discovered through the App JWT")
        check(stored_installation() == PULL_INSTALLATION_ID,
              "the discovered installation id is stored on the organization (the worker reads it there)")
        r = api("POST", "/repositories/connect-github", json={"repository": f"{OWNER}/{PULL_REPO}"})
        check(r.status_code == 200 and r.json()["data"]["id"] == repository_id,
              "connecting again returns the same repository")
        r = self.client.post("/api/v1/repositories/connect-github", headers=self.headers,
                             json={"repository": f"{OWNER}/{PULL_REPO}"})
        # 409: that organization is linked to another installation; 403: same installation, repo owned elsewhere.
        check(r.status_code in (403, 409), f"another organization cannot claim the repository ({r.status_code})")
        check(api("GET", f"/repositories/{repository_id}").json()["data"]["organization_id"] == str(self.pull_org_id),
              "the repository still belongs to the pull organization")

        r = api("POST", f"/repositories/{repository_id}/sync-pull-requests",
                params={"auto_analyze": "false"})
        check(r.status_code == 200 and [p["github_pr_number"] for p in r.json()["data"]] == [PR_NUMBER],
              f"sync pulled the open pull request without analyzing it ({r.status_code}: {r.text[:400]})")
        check(r.json()["meta"]["analysisIds"] == [], "auto_analyze=false queued nothing")

        r = api("POST", f"/repositories/{repository_id}/pull-requests/{PR_NUMBER}/analyze")
        check(r.status_code == 202, f"analyze-by-number accepted (got {r.status_code}: {r.text[:200]})")
        analysis_id = r.json()["data"]["id"]
        check(r.json()["data"]["commit_sha"] == self.head_sha and r.json()["data"]["status"] == "pending",
              "the head commit was read from GitHub and the analysis is pending")
        r = api("POST", f"/repositories/{repository_id}/sync-pull-requests")
        check(r.status_code == 200 and r.json()["meta"]["analysisIds"] == [],
              "a sync during a pending analysis queues no duplicate")
        r = api("POST", "/analyses", json={"repositoryId": repository_id,
                                            "pullRequestId": api("GET", f"/repositories/{repository_id}/pull-requests/{PR_NUMBER}").json()["data"]["id"],
                                            "commitSha": self.head_sha})
        check(r.status_code == 202 and r.json()["data"]["id"] == analysis_id,
              "POST /analyses (start_analysis) reuses the same pending analysis")

        self.run_worker()
        r = api("GET", f"/analyses/{analysis_id}")
        status = r.json()["data"]["status"]
        check(status == "completed", f"worker completed the analysis cloned with the stored installation (status={status})")
        check(not gh.unhandled and not self.github.unhandled,
              f"no unexpected GitHub API calls {gh.unhandled + self.github.unhandled}")
        r = api("GET", f"/analyses/{analysis_id}/verdict-v2")
        check(r.status_code == 200, f"verdict-v2 is available (got {r.status_code}: {r.text[:200]})")
        verdict = r.json()["data"]["verdict"]
        check(verdict == "insufficient_evidence",
              f"verdict is insufficient_evidence before CI results and confirmations (got {verdict})")
        self.assert_published(expected_verdict_label="insufficient", expect_rev=r.json()["data"]["revision"],
                              github=gh, analysis_id=analysis_id)
        check(len(gh.check_runs) == 1 and len(gh.comments) == 1,
              "one Check Run and one PR comment on the pull-demo repository")

        r = api("POST", f"/repositories/{repository_id}/sync-pull-requests")
        check(r.status_code == 200 and r.json()["meta"]["analysisIds"] == [],
              "a later sync does not re-analyze an already analyzed head commit")
        writes = len(gh.requests)
        self.run_worker()
        check(len(gh.requests) == writes, "an idle worker makes no GitHub calls")
        check(len(gh.check_runs) == 1 and len(gh.comments) == 1,
              "still exactly one Check Run and one comment after the repeat sync")
        check(self.webhook_calls == webhook_calls_before,
              "no webhook delivery was sent during the whole stage")

    def finish(self) -> None:
        if self.client is not None:
            self.client.__exit__(None, None, None)


def main() -> int:
    for entry in reversed(_pythonpath()):
        path = str(ROOT / entry)
        if path not in sys.path:
            sys.path.insert(0, path)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    base_url = os.environ.get("DATABASE_URL", "")
    keep_db = os.environ.get("RADIUS_SMOKE_KEEP_DB") == "1"  # read now: setup() scrubs RADIUS_* variables
    if not base_url:
        print("DATABASE_URL is required (PostgreSQL). Example: docker compose up -d postgres", file=sys.stderr)
        return 2

    started = time.monotonic()
    os.chdir(ROOT)
    workdir = Path(tempfile.mkdtemp(prefix="radius-smoke-"))
    database_url, name = create_database(base_url)
    smoke = Smoke(workdir, database_url)
    ok = False
    try:
        smoke.setup()
        smoke.health_and_auth()
        smoke.webhook_stage()
        smoke.worker_stage()
        smoke.ci_stage()
        smoke.confirm_stage()
        smoke.regression_stage()
        smoke.pull_stage()
        ok = True
    except SmokeFailure as exc:
        print(f"\nSMOKE FAILED: {exc}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        print("\nSMOKE ERROR:", file=sys.stderr)
        traceback.print_exc()
    finally:
        try:
            smoke.finish()
        finally:
            if keep_db:
                print(f"kept database {name} for manual inspection (RADIUS_SMOKE_KEEP_DB=1); drop it when done")
            else:
                drop_database(base_url, name)
            shutil.rmtree(workdir, ignore_errors=True)
    elapsed = time.monotonic() - started
    print(f"\n{'SMOKE PASSED' if ok else 'SMOKE FAILED'}: {len(STEPS)} checks in {elapsed:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
