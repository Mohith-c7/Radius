"""Security review A (API findings A-01..A-06, A-11, A-13, A-16): regression tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from radius_api.config import ApiSettings, get_api_settings
from radius_api.dependencies import get_github_client
from radius_api.github_pull import parse_owner_repo
from radius_api.main import create_app
from radius_github import GitHubAppClient, GitHubAppSettings
from radius_github.fake_app import FakeGitHubApp
from radius_repository.dto import UpsertPullRequestCommand
from radius_shared.database.base import Base
from radius_shared.database.models import Organization, Repository
from radius_shared.errors import ValidationError
from radius_shared.observability import metrics
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

SECRET = "webhook-test-secret"


def _repo_body(org: str, repo_id: int, clone_url: str, name="radius", owner="acme"):
    return {
        "organizationId": org,
        "repositoryId": repo_id,
        "name": name,
        "owner": owner,
        "defaultBranch": "main",
        "cloneUrl": clone_url,
        "visibility": "private",
    }


def _connect(client, org: str, repo_id: int = 101, clone_url="https://github.com/acme/radius.git"):
    return client.post(
        "/api/v1/repositories",
        headers={"X-Radius-Organization-Id": org},
        json=_repo_body(org, repo_id, clone_url),
    )


# --- A-01 / A-02: clone URL validation at the boundary ----------------------------

HOSTILE = [
    "--upload-pack=touch /tmp/pwned",
    "-c core.sshCommand=evil",
    "file:///var/lib/radius/cache/other-org/repo-1",
    "/var/lib/radius/cache/other-org/repo-1",
    "ext::sh -c 'touch /tmp/pwned'",
    "git@github.com:acme/radius.git",
    "ssh://git@github.com/acme/radius.git",
    "http://github.com/acme/radius.git",
    "https://attacker.example/acme/radius.git",
    "https://x-access-token:abc@github.com/acme/radius.git",
    "https://github.com@attacker.example/acme/radius.git",
    "https://github.com/acme/radius.git --upload-pack=x",
    "https://github.com/acme/radius.git\n",
    "https://github.com/../radius.git",
]


@pytest.mark.parametrize("url", HOSTILE)
def test_post_repositories_refuses_hostile_clone_urls(url: str) -> None:
    client = TestClient(create_app())
    org = str(uuid4())

    response = _connect(client, org, clone_url=url)

    assert response.status_code == 422, response.text
    listed = client.get("/api/v1/repositories", headers={"X-Radius-Organization-Id": org})
    assert listed.json()["data"] == []


def test_post_repositories_stores_the_canonical_https_url() -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    response = _connect(client, org, clone_url="https://GitHub.com/acme/radius")
    assert response.status_code == 201
    assert response.json()["data"]["clone_url"] == "https://github.com/acme/radius.git"


def test_enterprise_host_is_accepted_only_when_configured() -> None:
    app = create_app()
    client = TestClient(app)
    org = str(uuid4())
    ghes = "https://ghe.example.com/acme/radius.git"
    assert _connect(client, org, clone_url=ghes).status_code == 422

    app.state.settings.git_allowed_hosts = "ghe.example.com"
    assert _connect(client, org, clone_url=ghes).status_code == 201
    assert _connect(client, org, 102, "https://github.com/acme/radius.git").status_code == 422


def test_api_settings_reject_a_malformed_host_list() -> None:
    with pytest.raises(ValueError):
        ApiSettings(RADIUS_GIT_ALLOWED_HOSTS="good.example, bad host")


def _signed(body: bytes) -> dict[str, str]:
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": uuid4().hex,
        "X-Hub-Signature-256": signature,
    }


def _pr_payload(repo_id=404, clone_url="https://github.com/acme/radius.git", installation=None):
    payload = {
        "action": "synchronize",
        "repository": {
            "id": repo_id,
            "name": "radius",
            "private": True,
            "default_branch": "main",
            "clone_url": clone_url,
            "owner": {"login": "acme"},
        },
        "pull_request": {
            "number": 7,
            "title": "t",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "octocat"},
            "head": {"ref": "f", "sha": "d" * 40},
            "base": {"ref": "main", "sha": "e" * 40},
            "created_at": "2026-07-29T10:00:00Z",
            "merged_at": None,
        },
    }
    if installation is not None:
        payload["installation"] = {"id": installation}
    return payload


def _webhook_app(*, single_tenant=True):
    app = create_app()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_single_tenant = single_tenant
    app.state.settings.github_default_organization_id = uuid4()
    return app


def test_signed_webhook_with_a_hostile_clone_url_is_refused() -> None:
    app = _webhook_app()
    client = TestClient(app)
    for url in ("--upload-pack=x", "file:///etc", "https://attacker.example/a/b.git"):
        body = json.dumps(_pr_payload(clone_url=url)).encode()
        response = client.post("/api/v1/webhooks/github", content=body, headers=_signed(body))
        assert response.status_code == 422, (url, response.text)
    assert len(app.state.container.analysis_queue) == 0


# --- A-04: coverage tenancy ----------------------------------------------------


def _analysis(client, org: str, repo_id: int = 101) -> str:
    app = client.app
    repository = _connect(client, org, repo_id).json()["data"]["id"]
    from uuid import UUID

    pull_request = app.state.container.repository_service().upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(repository),
            github_pr_number=1,
            title="t",
            source_branch="f",
            target_branch="main",
            author="a",
            status="open",
            opened_at=datetime.now(UTC),
        )
    )
    started = client.post(
        "/api/v1/analyses",
        headers={"X-Radius-Organization-Id": org},
        json={
            "repositoryId": repository,
            "pullRequestId": str(pull_request.id),
            "commitSha": "a" * 40,
        },
    )
    assert started.status_code == 202, started.text
    return started.json()["data"]["id"]


def test_coverage_routes_enforce_the_tenant_boundary() -> None:
    client = TestClient(create_app())
    org_a, org_b = str(uuid4()), str(uuid4())
    analysis_id = _analysis(client, org_a)
    ingest = {
        "framework": "pytest",
        "coverage_percent": 91.0,
        "files": [
            {"test_id": "t1", "path": "a.py", "covered": True, "count": 1},
        ],
        "symbols": [],
    }

    # Cross-tenant write: org B cannot poison org A's analysis.
    write = client.post(
        "/api/v1/coverage",
        headers={
            "X-Radius-Organization-Id": org_b,
            "X-Analysis-Id": analysis_id,
        },
        json=ingest,
    )
    assert write.status_code == 404

    # The legitimate owner can.
    own = client.post(
        "/api/v1/coverage",
        headers={"X-Radius-Organization-Id": org_a, "X-Analysis-Id": analysis_id},
        json=ingest,
    )
    assert own.status_code == 202, own.text

    for path in ("", "/report"):
        owner_read = client.get(
            f"/api/v1/coverage/analysis/{analysis_id}{path}",
            headers={"X-Radius-Organization-Id": org_a},
        )
        assert owner_read.status_code == 200, (path, owner_read.text)
        foreign = client.get(
            f"/api/v1/coverage/analysis/{analysis_id}{path}",
            headers={"X-Radius-Organization-Id": org_b},
        )
        assert foreign.status_code == 404, (path, foreign.text)
        missing = client.get(
            f"/api/v1/coverage/analysis/{uuid4()}{path}",
            headers={"X-Radius-Organization-Id": org_b},
        )
        assert missing.status_code == 404  # indistinguishable from "foreign"


def test_coverage_ingest_rejects_malformed_ids_with_4xx() -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    bad = client.post(
        "/api/v1/coverage",
        headers={"X-Radius-Organization-Id": org, "X-Analysis-Id": "not-a-uuid"},
        json={},
    )
    assert bad.status_code == 422


# --- A-05: registration is org-scoped -------------------------------------------


def test_post_repositories_does_not_return_or_take_over_another_orgs_repository() -> None:
    client = TestClient(create_app())
    org_a, org_b = str(uuid4()), str(uuid4())
    original = _connect(client, org_a, 555).json()["data"]

    squat = _connect(client, org_b, 555)

    assert squat.status_code == 409
    leaked = squat.text
    assert original["id"] not in leaked
    assert org_a not in leaked
    assert "clone_url" not in leaked
    # org A's repository is untouched and org B owns nothing.
    assert client.get(
        f"/api/v1/repositories/{original['id']}",
        headers={"X-Radius-Organization-Id": org_a},
    ).status_code == 200
    assert client.get(
        "/api/v1/repositories", headers={"X-Radius-Organization-Id": org_b}
    ).json()["data"] == []
    # Same org re-registering stays idempotent.
    assert _connect(client, org_a, 555).status_code == 201


def test_repository_ids_do_not_reveal_other_tenants_repositories() -> None:
    client = TestClient(create_app())
    org_a, org_b = str(uuid4()), str(uuid4())
    repo = _connect(client, org_a, 556).json()["data"]["id"]
    foreign = client.get(
        f"/api/v1/repositories/{repo}", headers={"X-Radius-Organization-Id": org_b}
    )
    unknown = client.get(
        f"/api/v1/repositories/{uuid4()}", headers={"X-Radius-Organization-Id": org_b}
    )
    assert foreign.status_code == unknown.status_code == 404
    for verb in ("delete",):
        assert (
            getattr(client, verb)(
                f"/api/v1/repositories/{repo}",
                headers={"X-Radius-Organization-Id": org_b},
            ).status_code
            == 404
        )


@pytest.fixture
def sql_env(tmp_path: Path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("GITHUB_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("GITHUB_DEFAULT_ORGANIZATION_ID", raising=False)
    get_api_settings.cache_clear()
    yield engine
    get_api_settings.cache_clear()
    engine.dispose()


def test_webhook_routes_to_the_org_that_owns_the_installation_not_a_squatter(sql_env) -> None:
    owner_org, squatter, repo_id = uuid4(), uuid4(), 9001
    with Session(sql_env) as session:
        session.add(Organization(id=owner_org, name="Victim", github_installation_id=111))
        session.add(Organization(id=squatter, name="Squatter"))
        session.commit()
    app = create_app()
    client = TestClient(app)
    # The squatter registers the victim's numeric repository id first.
    assert _connect(client, str(squatter), repo_id).status_code == 201

    # The victim's signed delivery (their installation) must NOT land on the squatter.
    body = json.dumps(_pr_payload(repo_id=repo_id, installation=111)).encode()
    response = client.post("/api/v1/webhooks/github", content=body, headers=_signed(body))

    assert response.status_code == 403, response.text
    with Session(sql_env) as session:
        assert session.get(Organization, squatter).github_installation_id is None
        rows = session.query(Repository).all()
        assert [r.organization_id for r in rows] == [squatter]


def test_unknown_installation_cannot_bind_to_a_squatted_repository(sql_env) -> None:
    squatter = uuid4()
    with Session(sql_env) as session:
        session.add(Organization(id=squatter, name="Squatter"))
        session.commit()
    app = create_app()
    app.state.settings.github_dev_single_tenant = False
    client = TestClient(app)
    assert _connect(client, str(squatter), 9002).status_code == 201

    body = json.dumps(_pr_payload(repo_id=9002, installation=777)).encode()
    response = client.post("/api/v1/webhooks/github", content=body, headers=_signed(body))

    assert response.status_code == 403
    with Session(sql_env) as session:
        assert session.get(Organization, squatter).github_installation_id is None


def test_installation_is_not_adopted_by_a_webhook_outside_single_tenant_modes(sql_env) -> None:
    org = uuid4()
    with Session(sql_env) as session:
        session.add(Organization(id=org, name="Acme"))
        session.commit()
    app = create_app()
    app.state.settings.github_default_organization_id = org
    app.state.settings.github_single_tenant = True  # explicit single-tenant: adoption allowed
    client = TestClient(app)
    body = json.dumps(_pr_payload(repo_id=9003, installation=888)).encode()
    assert client.post("/api/v1/webhooks/github", content=body, headers=_signed(body)).status_code == 202
    with Session(sql_env) as session:
        assert session.get(Organization, org).github_installation_id == 888


# --- A-03: connect-github needs a prior installation binding -----------------------


@pytest.fixture(scope="module")
def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return private, public


class _Github:
    def __init__(self, key_pair, sql_env, *, dev_single_tenant: bool):
        private, public = key_pair
        self.fake = FakeGitHubApp(public_key_pem=public)
        client = GitHubAppClient(
            GitHubAppSettings(GITHUB_APP_ID="12345", GITHUB_APP_PRIVATE_KEY=private),
            opener=self.fake.opener,
            sleep=lambda _s: None,
        )
        self.app = create_app()
        self.app.state.settings.github_dev_single_tenant = dev_single_tenant
        self.app.dependency_overrides[get_github_client] = lambda: client
        self.http = TestClient(self.app)
        self.engine = sql_env

    def new_org(self, installation_id=None) -> str:
        org = uuid4()
        with Session(self.engine) as session:
            session.add(Organization(id=org, name="o", github_installation_id=installation_id))
            session.commit()
        return str(org)

    def installation_of(self, org: str):
        from uuid import UUID

        with Session(self.engine) as session:
            return session.get(Organization, UUID(org)).github_installation_id

    def connect(self, org: str, repository="acme/widgets"):
        return self.http.post(
            "/api/v1/repositories/connect-github",
            headers={"X-Radius-Organization-Id": org},
            json={"repository": repository},
        )


def test_connect_github_does_not_adopt_an_installation_outside_dev_mode(key_pair, sql_env) -> None:
    gh = _Github(key_pair, sql_env, dev_single_tenant=False)
    org = gh.new_org()

    response = gh.connect(org)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "GITHUB_INSTALLATION_NOT_LINKED"
    assert gh.installation_of(org) is None
    # GitHub was not even asked, so this route is no oracle for private repositories.
    assert not any("/installation" in path for _, path in gh.fake.requests)
    with Session(sql_env) as session:
        assert session.query(Repository).count() == 0


def test_connect_github_works_for_an_org_already_bound_to_that_installation(key_pair, sql_env) -> None:
    gh = _Github(key_pair, sql_env, dev_single_tenant=False)
    org = gh.new_org(installation_id=9001)  # FakeGitHubApp installation id

    response = gh.connect(org)

    assert response.status_code == 201, response.text
    assert gh.installation_of(org) == 9001


def test_connect_github_refuses_an_installation_bound_to_another_org(key_pair, sql_env) -> None:
    gh = _Github(key_pair, sql_env, dev_single_tenant=True)
    owner = gh.new_org(installation_id=9001)
    intruder = gh.new_org()

    response = gh.connect(intruder)

    assert response.status_code == 409
    assert gh.installation_of(intruder) is None
    assert gh.installation_of(owner) == 9001


def test_connect_github_dev_single_tenant_mode_keeps_the_demo_path_working(key_pair, sql_env) -> None:
    gh = _Github(key_pair, sql_env, dev_single_tenant=True)
    org = gh.new_org()

    response = gh.connect(org)

    assert response.status_code == 201, response.text
    assert gh.installation_of(org) == 9001
    again = gh.connect(org)
    assert again.status_code == 200


def test_connect_github_refuses_a_different_installation_than_the_bound_one(key_pair, sql_env) -> None:
    gh = _Github(key_pair, sql_env, dev_single_tenant=True)
    org = gh.new_org(installation_id=4242)

    response = gh.connect(org)

    assert response.status_code == 409
    assert gh.installation_of(org) == 4242


def test_dev_single_tenant_defaults_follow_the_environment() -> None:
    assert ApiSettings(RADIUS_ENV="development").github_dev_single_tenant is True
    assert ApiSettings(RADIUS_ENV="test").github_dev_single_tenant is False
    assert (
        ApiSettings(
            RADIUS_ENV="production", RADIUS_API_KEY_PEPPER="p" * 40
        ).github_dev_single_tenant
        is False
    )
    assert (
        ApiSettings(
            RADIUS_ENV="development", RADIUS_GITHUB_DEV_SINGLE_TENANT="false"
        ).github_dev_single_tenant
        is False
    )


# --- A-06: analyses ------------------------------------------------------------


def test_start_analysis_rejects_a_pull_request_of_another_repository() -> None:
    from uuid import UUID

    client = TestClient(create_app())
    org_a, org_b = str(uuid4()), str(uuid4())
    repo_a = _connect(client, org_a, 1).json()["data"]["id"]
    repo_b = _connect(client, org_b, 2, "https://github.com/other/thing.git").json()["data"]["id"]
    service = client.app.state.container.repository_service()
    pr_of_a = service.upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(repo_a),
            github_pr_number=1,
            title="t",
            source_branch="f",
            target_branch="main",
            author="a",
            status="open",
            opened_at=datetime.now(UTC),
        )
    )

    # Org B analyses its own repository but names org A's pull request.
    response = client.post(
        "/api/v1/analyses",
        headers={"X-Radius-Organization-Id": org_b},
        json={"repositoryId": repo_b, "pullRequestId": str(pr_of_a.id), "commitSha": "a" * 40},
    )
    assert response.status_code == 404
    assert len(client.app.state.container.analysis_queue) == 0


@pytest.mark.parametrize(
    "sha", ["-f", "--orphan=x", "a/b", "../x", "abc", "g" * 40, "a" * 41, "a" * 6, ""]
)
def test_start_analysis_rejects_malformed_commit_shas(sha: str) -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    repo = _connect(client, org, 3).json()["data"]["id"]
    response = client.post(
        "/api/v1/analyses",
        headers={"X-Radius-Organization-Id": org},
        json={"repositoryId": repo, "pullRequestId": str(uuid4()), "commitSha": sha},
    )
    assert response.status_code == 422


# --- A-11: webhook robustness -----------------------------------------------------


def test_non_ascii_signature_header_is_403_not_500() -> None:
    client = TestClient(_webhook_app())
    body = json.dumps(_pr_payload()).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "d-1",
        "X-Hub-Signature-256": "sha256=café".encode("latin-1"),
    }
    response = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert response.status_code == 403


def test_missing_signature_is_refused_before_the_body_matters() -> None:
    client = TestClient(_webhook_app())
    response = client.post(
        "/api/v1/webhooks/github",
        content=b"x" * 10_000,
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "d-2"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("repo_id", ["abc", "1.5", [1], {"x": 1}, True, "٣"])
def test_non_integer_repository_id_is_a_client_error(repo_id) -> None:
    client = TestClient(_webhook_app(single_tenant=False))
    payload = _pr_payload()
    payload["repository"]["id"] = repo_id
    body = json.dumps(payload).encode()
    response = client.post("/api/v1/webhooks/github", content=body, headers=_signed(body))
    assert 400 <= response.status_code < 500, response.text


def test_webhook_body_cap_default_is_five_mebibytes() -> None:
    assert ApiSettings().webhook_max_body_bytes == 5 * 1024 * 1024


# --- A-13: dot segments ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["../..", "./x", "x/.", "x/..", "../app", "https://github.com/../x", ".//."]
)
def test_parse_owner_repo_rejects_dot_segments(value: str) -> None:
    with pytest.raises(ValidationError):
        parse_owner_repo(value)


def test_parse_owner_repo_still_accepts_normal_names() -> None:
    assert parse_owner_repo("acme/widgets") == ("acme", "widgets")
    assert parse_owner_repo("https://github.com/acme/wid.gets.git") == ("acme", "wid.gets")
    assert parse_owner_repo("a.b/.github") == ("a.b", ".github")


# --- A-16: /metrics gate ---------------------------------------------------------------


@pytest.fixture
def metrics_on(monkeypatch):
    monkeypatch.setenv("RADIUS_METRICS_ENABLED", "true")
    yield
    metrics.configure_metrics(False)


def test_metrics_is_open_in_development_without_a_token(metrics_on) -> None:
    assert TestClient(create_app()).get("/metrics").status_code == 200


def test_metrics_requires_the_bearer_token_when_configured(metrics_on, monkeypatch) -> None:
    token = "m" + uuid4().hex
    monkeypatch.setenv("RADIUS_METRICS_TOKEN", token)
    client = TestClient(create_app())
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_metrics_is_off_in_production_like_modes_without_a_token(metrics_on, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ENV", "uat")
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", "p" * 40)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("SESSION_SECRET", uuid4().hex + uuid4().hex)
    get_api_settings.cache_clear()
    try:
        assert TestClient(create_app()).get("/metrics").status_code == 404
    finally:
        get_api_settings.cache_clear()
