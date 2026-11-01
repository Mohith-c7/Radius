"""GET /analyses/lookup: resolve an analysis by repository, PR number and head SHA."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_repository.dto import UpsertPullRequestCommand

HEAD = "c0ffee" + "0" * 34
OTHER = "d" * 40


def _setup(client: TestClient, app, organization_id: str, *, owner="Acme", name="Radius"):
    headers = {"X-Radius-Organization-Id": organization_id}
    repository = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": organization_id,
            "repositoryId": int(uuid4().int % 1_000_000),
            "name": name,
            "owner": owner,
            "defaultBranch": "main",
            "cloneUrl": f"https://github.com/{owner}/{name}.git",
            "visibility": "private",
        },
    )
    assert repository.status_code == 201, repository.text
    repository_id = repository.json()["data"]["id"]
    pull_request = app.state.container.repository_service().upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(repository_id),
            github_pr_number=12,
            title="Feature",
            source_branch="feature",
            target_branch="main",
            author="octocat",
            status="open",
            opened_at=datetime.now(UTC),
        )
    )
    return headers, repository_id, str(pull_request.id)


def _start(client, headers, repository_id, pull_request_id, sha):
    response = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repository_id, "pullRequestId": pull_request_id, "commitSha": sha},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["id"]


def test_lookup_resolves_analysis_for_pr_head_commit() -> None:
    app = create_app()
    client = TestClient(app)
    org = str(uuid4())
    headers, repository_id, pull_request_id = _setup(client, app, org)
    older = _start(client, headers, repository_id, pull_request_id, OTHER)
    target = _start(client, headers, repository_id, pull_request_id, HEAD)

    by_name = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        # owner/name match is case-insensitive, like GitHub's.
        params={"repository": "acme/radius", "pullRequest": 12, "commitSha": HEAD.upper()},
    )
    by_id = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repositoryId": repository_id, "pullRequest": 12, "commitSha": HEAD[:12]},
    )

    assert by_name.status_code == 200, by_name.text
    assert by_name.json()["data"]["id"] == target
    assert by_name.json()["data"]["status"] == "pending"
    assert by_id.json()["data"]["id"] == target
    assert target != older


def test_lookup_returns_newest_analysis_for_rerun_commit() -> None:
    app = create_app()
    client = TestClient(app)
    headers, repository_id, pull_request_id = _setup(client, app, str(uuid4()))
    first = _start(client, headers, repository_id, pull_request_id, HEAD)
    rerun = client.post(f"/api/v1/analyses/{first}/rerun", headers=headers).json()["data"]["id"]

    response = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "Acme/Radius", "pullRequest": 12, "commitSha": HEAD},
    )

    assert response.json()["data"]["id"] == rerun


def test_lookup_404_when_commit_not_analysed_yet() -> None:
    app = create_app()
    client = TestClient(app)
    headers, repository_id, pull_request_id = _setup(client, app, str(uuid4()))
    _start(client, headers, repository_id, pull_request_id, OTHER)

    response = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "acme/radius", "pullRequest": 12, "commitSha": HEAD},
    )

    assert response.status_code == 404
    assert "No analysis found" in response.json()["error"]["message"]


def test_lookup_unknown_pull_request_or_repository_is_404() -> None:
    app = create_app()
    client = TestClient(app)
    headers, _, _ = _setup(client, app, str(uuid4()))

    unknown_pr = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "acme/radius", "pullRequest": 99, "commitSha": HEAD},
    )
    unknown_repo = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "acme/other", "pullRequest": 12, "commitSha": HEAD},
    )

    assert unknown_pr.status_code == 404
    assert unknown_repo.status_code == 404


def test_lookup_is_scoped_to_the_callers_organization() -> None:
    app = create_app()
    client = TestClient(app)
    headers, repository_id, pull_request_id = _setup(client, app, str(uuid4()))
    _start(client, headers, repository_id, pull_request_id, HEAD)
    intruder = {"X-Radius-Organization-Id": str(uuid4())}

    by_name = client.get(
        "/api/v1/analyses/lookup",
        headers=intruder,
        params={"repository": "acme/radius", "pullRequest": 12, "commitSha": HEAD},
    )
    by_id = client.get(
        "/api/v1/analyses/lookup",
        headers=intruder,
        params={"repositoryId": repository_id, "pullRequest": 12, "commitSha": HEAD},
    )

    # Another tenant's repository is invisible by name and forbidden by id.
    assert by_name.status_code == 404
    assert by_id.status_code == 403


def test_lookup_validates_inputs() -> None:
    app = create_app()
    client = TestClient(app)
    headers, _, _ = _setup(client, app, str(uuid4()))

    bad_sha = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "acme/radius", "pullRequest": 12, "commitSha": "not-hex"},
    )
    no_repo = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"pullRequest": 12, "commitSha": HEAD},
    )
    missing_pr = client.get(
        "/api/v1/analyses/lookup",
        headers=headers,
        params={"repository": "acme/radius", "commitSha": HEAD},
    )

    assert bad_sha.status_code == 422
    assert no_repo.status_code == 422
    assert missing_pr.status_code == 422
