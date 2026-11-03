"""Pull-based GitHub flow: connect by name, sync and analyze without a webhook.

The real ``GitHubAppClient`` (RS256 JWT signing included) runs against the
in-memory ``FakeGitHubApp``; nothing here touches the network.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from radius_api.dependencies import get_github_client
from radius_api.main import create_app
from radius_github import GitHubAppClient, GitHubAppSettings
from radius_github.fake_app import FakeGitHubApp

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


class Env:
    def __init__(self, key_pair: tuple[str, str], *, configured: bool = True) -> None:
        private, public = key_pair
        self.github = FakeGitHubApp(public_key_pem=public)
        self.github.add_pull(7, head_sha=SHA_A, title="Add discount", body="Adds it.")
        self.github.add_pull(8, head_sha=SHA_B, title="WIP", draft=True)
        settings = GitHubAppSettings(
            GITHUB_APP_ID="12345" if configured else "",
            GITHUB_APP_PRIVATE_KEY=private if configured else "",
        )
        client = GitHubAppClient(
            settings, opener=self.github.opener, sleep=lambda _s: None
        )
        self.app = create_app()
        self.app.dependency_overrides[get_github_client] = lambda: client
        self.http = TestClient(self.app)
        self.org = str(uuid4())
        self.headers = {"X-Radius-Organization-Id": self.org}

    def post(self, path: str, **kwargs):
        return self.http.post(f"/api/v1{path}", headers=self.headers, **kwargs)

    def get(self, path: str):
        return self.http.get(f"/api/v1{path}", headers=self.headers)

    def connect(self, repository: str = "acme/widgets"):
        return self.post("/repositories/connect-github", json={"repository": repository})


@pytest.fixture
def env(key_pair) -> Env:
    return Env(key_pair)


def test_connect_by_name_needs_no_webhook_and_no_installation_id(env: Env) -> None:
    response = env.connect()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["data"]["full_name"] == "acme/widgets"
    assert body["data"]["default_branch"] == "main"
    assert body["data"]["clone_url"] == "https://github.com/acme/widgets.git"
    assert body["data"]["visibility"] == "private"
    assert body["meta"] == {"installationId": 9001, "created": True}
    assert ("GET", "/repos/acme/widgets/installation") in env.github.requests
    assert env.github.jwt_verified >= 1

    again = env.connect("https://github.com/acme/widgets.git")
    assert again.status_code == 200
    assert again.json()["data"]["id"] == body["data"]["id"]
    assert again.json()["meta"]["created"] is False
    listed = env.get("/repositories").json()["data"]
    assert [item["id"] for item in listed] == [body["data"]["id"]]


def test_connect_reports_app_not_installed(env: Env) -> None:
    env.github.installed = False

    response = env.connect()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GITHUB_REPOSITORY_NOT_ACCESSIBLE"
    assert "not installed" in response.json()["error"]["message"]


def test_connect_reports_bad_app_credentials_without_secrets(env: Env) -> None:
    env.github.app_id = "99999"  # JWT issuer no longer matches this App

    response = env.connect()

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "GITHUB_APP_AUTH_FAILED"
    assert "clock" in error["message"]
    assert "BEGIN" not in response.text


def test_connect_without_credentials_is_an_actionable_conflict(key_pair) -> None:
    unconfigured = Env(key_pair, configured=False)

    response = unconfigured.connect()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GITHUB_APP_NOT_CONFIGURED"
    assert "GITHUB_APP_PRIVATE_KEY" in response.json()["error"]["message"]


@pytest.mark.parametrize("value", ["acme", "a/b/c", "acme/", "ac me/widgets", ""])
def test_connect_rejects_malformed_repository_names(env: Env, value: str) -> None:
    assert env.connect(value).status_code == 422


def test_another_organization_cannot_take_over_a_connected_repository(env: Env) -> None:
    assert env.connect().status_code == 201

    intruder = env.http.post(
        "/api/v1/repositories/connect-github",
        headers={"X-Radius-Organization-Id": str(uuid4())},
        json={"repository": "acme/widgets"},
    )

    assert intruder.status_code == 403


def test_analyze_pull_request_by_number_reads_head_sha_from_github(env: Env) -> None:
    repository_id = env.connect().json()["data"]["id"]

    response = env.post(f"/repositories/{repository_id}/pull-requests/7/analyze")

    assert response.status_code == 202, response.text
    analysis = response.json()["data"]
    assert analysis["commit_sha"] == SHA_A
    assert analysis["status"] == "pending"
    assert ("GET", "/repos/acme/widgets/pulls/7") in env.github.requests
    stored = env.get(f"/repositories/{repository_id}/pull-requests/7").json()["data"]
    assert stored["title"] == "Add discount"
    assert stored["status"] == "open"

    repeated = env.post(f"/repositories/{repository_id}/pull-requests/7/analyze")
    assert repeated.json()["data"]["id"] == analysis["id"], "pending analysis is reused"

    env.github.pulls[0]["head"]["sha"] = SHA_B  # new commit pushed
    moved = env.post(f"/repositories/{repository_id}/pull-requests/7/analyze")
    assert moved.json()["data"]["id"] != analysis["id"]
    assert moved.json()["data"]["commit_sha"] == SHA_B

    lookup = env.get(
        "/analyses/lookup?repository=acme/widgets&pullRequest=7&commitSha=" + SHA_B
    )
    assert lookup.status_code == 200
    assert lookup.json()["data"]["id"] == moved.json()["data"]["id"]


def test_analyze_unknown_pull_request_is_a_clear_404(env: Env) -> None:
    repository_id = env.connect().json()["data"]["id"]

    response = env.post(f"/repositories/{repository_id}/pull-requests/999/analyze")

    assert response.status_code == 404
    assert "999" in response.json()["error"]["message"]


def test_analyze_requires_a_connected_repository_of_the_same_organization(env: Env) -> None:
    repository_id = env.connect().json()["data"]["id"]

    other = env.http.post(
        f"/api/v1/repositories/{repository_id}/pull-requests/7/analyze",
        headers={"X-Radius-Organization-Id": str(uuid4())},
    )
    assert other.status_code == 403

    env.http.delete(f"/api/v1/repositories/{repository_id}", headers=env.headers)
    disconnected = env.post(f"/repositories/{repository_id}/pull-requests/7/analyze")
    assert disconnected.status_code == 409
    assert disconnected.json()["error"]["code"] == "REPOSITORY_DISCONNECTED"


def test_sync_pulls_open_prs_and_skips_drafts_for_analysis(env: Env) -> None:
    repository_id = env.connect().json()["data"]["id"]

    response = env.post(f"/repositories/{repository_id}/sync-pull-requests")

    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(pr["github_pr_number"] for pr in body["data"]) == [7, 8]
    assert body["meta"]["github"] == "synced"
    assert len(body["meta"]["analysisIds"]) == 1, "the draft is stored, not analyzed"
    analyses = env.get(f"/analyses?repositoryId={repository_id}").json()["data"]
    assert [a["commit_sha"] for a in analyses] == [SHA_A]

    repeat = env.post(f"/repositories/{repository_id}/sync-pull-requests")
    assert repeat.json()["meta"]["analysisIds"] == [], "same head commit is not queued twice"

    no_analysis = env.post(f"/repositories/{repository_id}/sync-pull-requests?auto_analyze=false")
    assert no_analysis.json()["meta"]["analysisIds"] == []
    assert len(env.get(f"/analyses?repositoryId={repository_id}").json()["data"]) == 1


def test_sync_surfaces_github_failures_instead_of_swallowing_them(env: Env) -> None:
    repository_id = env.connect().json()["data"]["id"]
    env.github.fail[("GET", "/repos/acme/widgets/pulls")] = 403

    response = env.post(f"/repositories/{repository_id}/sync-pull-requests")

    assert response.status_code == 403
    assert "listing pull requests" in response.json()["error"]["message"]


def test_sync_without_credentials_returns_stored_pull_requests(key_pair) -> None:
    unconfigured = Env(key_pair, configured=False)
    created = unconfigured.post(
        "/repositories",
        json={
            "organizationId": unconfigured.org,
            "repositoryId": 5,
            "name": "widgets",
            "owner": "acme",
            "cloneUrl": "https://github.com/acme/widgets.git",
        },
    )
    repository_id = created.json()["data"]["id"]

    response = unconfigured.post(f"/repositories/{repository_id}/sync-pull-requests")

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"] == {"github": "not_configured"}
    assert unconfigured.github.requests == []
