"""C-11: list endpoints are paginated (limit/offset, hard maximum) and report totals."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_api.pagination import DEFAULT_LIMIT, MAX_LIMIT


@pytest.fixture
def seeded():
    client = TestClient(create_app())
    organization_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": organization_id}
    repository_ids = []
    for number in range(3):
        response = client.post(
            "/api/v1/repositories",
            headers=headers,
            json={
                "organizationId": organization_id,
                "repositoryId": 900 + number,
                "name": f"repo-{number}",
                "owner": "acme",
                "defaultBranch": "main",
                "cloneUrl": f"https://github.com/acme/repo-{number}.git",
                "visibility": "private",
            },
        )
        repository_ids.append(response.json()["data"]["id"])
    analysis_ids = []
    for index in range(5):
        response = client.post(
            "/api/v1/analyses",
            headers=headers,
            json={
                "repositoryId": repository_ids[index % 2],
                "pullRequestId": str(uuid4()),
                "commitSha": f"{index:x}" * 40,
            },
        )
        assert response.status_code == 202
        analysis_ids.append(response.json()["data"]["id"])
    return client, headers, repository_ids, analysis_ids


def test_analyses_default_page_reports_totals_and_keeps_the_list_shape(seeded) -> None:
    client, headers, _repos, analysis_ids = seeded
    response = client.get("/api/v1/analyses", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["data"], list)  # compatibility: still a plain list
    assert {item["id"] for item in body["data"]} == set(analysis_ids)
    assert body["meta"]["pagination"] == {
        "limit": DEFAULT_LIMIT,
        "offset": 0,
        "total": 5,
        "returned": 5,
    }


def test_limit_and_offset_page_through_all_analyses_without_overlap(seeded) -> None:
    client, headers, _repos, analysis_ids = seeded
    seen: list[str] = []
    for offset in (0, 2, 4):
        page = client.get("/api/v1/analyses", headers=headers, params={"limit": 2, "offset": offset})
        body = page.json()
        assert body["meta"]["pagination"]["total"] == 5
        assert len(body["data"]) == (2 if offset < 4 else 1)
        seen.extend(item["id"] for item in body["data"])
    assert sorted(seen) == sorted(analysis_ids) and len(set(seen)) == 5


def test_filters_still_apply_with_pagination(seeded) -> None:
    client, headers, repos, _ids = seeded
    response = client.get(
        "/api/v1/analyses", headers=headers, params={"repositoryId": repos[1], "limit": 1}
    )
    body = response.json()
    assert body["meta"]["pagination"]["total"] == 2 and len(body["data"]) == 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": MAX_LIMIT + 1}, {"offset": -1}, {"limit": "x"}])
def test_out_of_range_page_parameters_are_rejected(seeded, params) -> None:
    client, headers, repos, _ids = seeded
    for path in (
        "/api/v1/analyses",
        "/api/v1/repositories",
        f"/api/v1/repositories/{repos[0]}/pull-requests",
    ):
        assert client.get(path, headers=headers, params=params).status_code == 422, path


def test_maximum_page_size_is_accepted(seeded) -> None:
    client, headers, _repos, _ids = seeded
    assert client.get("/api/v1/analyses", headers=headers, params={"limit": MAX_LIMIT}).status_code == 200


def test_repositories_and_pull_requests_lists_are_paginated(seeded) -> None:
    client, headers, repos, _ids = seeded
    page = client.get("/api/v1/repositories", headers=headers, params={"limit": 2})
    body = page.json()
    assert len(body["data"]) == 2
    assert body["meta"]["pagination"] == {"limit": 2, "offset": 0, "total": 3, "returned": 2}
    rest = client.get("/api/v1/repositories", headers=headers, params={"limit": 2, "offset": 2})
    assert len(rest.json()["data"]) == 1
    prs = client.get(f"/api/v1/repositories/{repos[0]}/pull-requests", headers=headers)
    assert prs.json()["meta"]["pagination"]["total"] == 0 and prs.json()["data"] == []


def test_org_wide_listing_does_not_look_up_each_repository(seeded, monkeypatch) -> None:
    """The N+1: one repository lookup per repository before the fix."""

    client, headers, _repos, _ids = seeded
    from radius_repository.application import RepositoryApplicationService

    calls = {"get_repository": 0}
    original = RepositoryApplicationService.get_repository

    def counting(self, repository_id):
        calls["get_repository"] += 1
        return original(self, repository_id)

    monkeypatch.setattr(RepositoryApplicationService, "get_repository", counting)
    assert client.get("/api/v1/analyses", headers=headers).status_code == 200
    assert calls["get_repository"] == 0
