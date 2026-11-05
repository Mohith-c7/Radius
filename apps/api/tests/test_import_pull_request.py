"""Analyse a public GitHub pull request from its link (no GitHub App)."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_api.routes import repositories as repositories_routes

REPO = {
    "id": 4242,
    "name": "demo",
    "private": False,
    "default_branch": "main",
    "clone_url": "https://github.com/octo/demo.git",
    "owner": {"login": "octo"},
}
PR = {
    "number": 7,
    "title": "Fix the parser",
    "state": "open",
    "draft": False,
    "merged": False,
    "user": {"login": "contributor"},
    "head": {"ref": "fix-parser", "sha": "a" * 40},
    "base": {"ref": "main", "sha": "b" * 40},
    "created_at": "2026-11-01T10:00:00Z",
    "merged_at": None,
}


@pytest.fixture
def github(monkeypatch):
    calls: list[str] = []

    def fake_get(path: str) -> dict:
        calls.append(path)
        return REPO if path == "/repos/octo/demo" else PR

    monkeypatch.setattr(repositories_routes, "_github_get", fake_get)
    return calls


def test_import_connects_repo_and_queues_analysis(github) -> None:
    client = TestClient(create_app())
    org = str(uuid4())
    headers = {"X-Radius-Organization-Id": org}

    response = client.post(
        "/api/v1/repositories/import-pull-request",
        headers=headers,
        json={"url": "https://github.com/octo/demo/pull/7/files"},
    )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["repository"] == "octo/demo"
    assert data["pullRequestNumber"] == 7
    assert data["commitSha"] == "a" * 40
    assert github == ["/repos/octo/demo", "/repos/octo/demo/pulls/7"]

    analysis = client.get(f"/api/v1/analyses/{data['analysisId']}", headers=headers).json()["data"]
    assert analysis["commit_sha"] == "a" * 40
    repos = client.get("/api/v1/repositories", headers=headers).json()["data"]
    assert [r["github_repository_id"] for r in repos] == [4242]

    # A second PR link for the same repo reuses the connected repository.
    again = client.post(
        "/api/v1/repositories/import-pull-request",
        headers=headers,
        json={"url": "github.com/octo/demo/pull/7"},
    )
    assert again.status_code == 202
    assert again.json()["data"]["repositoryId"] == data["repositoryId"]


@pytest.mark.parametrize(
    "url",
    ["not a link", "https://github.com/octo/demo", "https://github.com/octo/demo/issues/7"],
)
def test_import_rejects_links_that_are_not_pull_requests(github, url) -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/repositories/import-pull-request",
        headers={"X-Radius-Organization-Id": str(uuid4())},
        json={"url": url},
    )

    assert response.status_code == 422
    assert "pull request link" in response.json()["error"]["message"]
    assert github == []


def test_import_refuses_private_repositories(monkeypatch) -> None:
    monkeypatch.setattr(
        repositories_routes,
        "_github_get",
        lambda path: dict(REPO, private=True) if path == "/repos/octo/demo" else PR,
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/repositories/import-pull-request",
        headers={"X-Radius-Organization-Id": str(uuid4())},
        json={"url": "https://github.com/octo/demo/pull/7"},
    )

    assert response.status_code == 422
    assert "private" in response.json()["error"]["message"]
