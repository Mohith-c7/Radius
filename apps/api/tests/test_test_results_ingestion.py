"""Tests for test results ingestion endpoint."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def _setup_analysis(client: TestClient, headers: dict[str, str]) -> tuple[UUID, UUID]:
    org_id = headers["X-Radius-Organization-Id"]
    repo_res = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": org_id,
            "repositoryId": 601,
            "name": "test-ingest-repo",
            "owner": "radius-ingest",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/radius-ingest/test-ingest-repo.git",
            "visibility": "private",
        },
    )
    repo_id = UUID(repo_res.json()["data"]["id"])

    analysis_res = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": str(repo_id),
            "pullRequestId": str(uuid4()),
            "commitSha": "f" * 40,
        },
    )
    analysis_id = UUID(analysis_res.json()["data"]["id"])
    return repo_id, analysis_id


def test_ingest_junit_xml_successful() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    junit_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" errors="0" failures="0" skipped="0" time="0.123">
    <testcase classname="tests.test_auth" name="test_login" time="0.045"/>
    <testcase classname="tests.test_auth" name="test_token" time="0.035"/>
    <testcase classname="tests.test_core" name="test_config" time="0.043"/>
</testsuite>
"""

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/xml"},
        content=junit_xml,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total_tests"] == 3
    assert data["passed"] == 3
    assert data["failed"] == 0

    # Verify confidence report was updated
    conf_response = client.get(
        f"/api/v1/analyses/{analysis_id}/confidence",
        headers=headers,
    )
    assert conf_response.status_code == 200
    conf_body = conf_response.json()
    assert conf_body["success"] is True
    conf_data = conf_body["data"]
    # No analysis recorded which changed files these tests exercise, so passing
    # CI results alone must not produce a "verified"/low-risk verdict.
    assert conf_data["verification_status"] == "insufficient_evidence"
    assert conf_data["confidence_score"] <= 69


def test_ingest_junit_xml_with_failures_reduces_confidence() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    # First ingest passing results to establish a baseline
    passing_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" errors="0" failures="0" skipped="0" time="0.100">
    <testcase classname="tests.test_auth" name="test_1" time="0.030"/>
    <testcase classname="tests.test_auth" name="test_2" time="0.030"/>
    <testcase classname="tests.test_auth" name="test_3" time="0.040"/>
</testsuite>
"""
    client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/xml"},
        content=passing_xml,
    )
    baseline_conf = client.get(
        f"/api/v1/analyses/{analysis_id}/confidence",
        headers=headers,
    ).json()["data"]["confidence_score"]

    # Ingest JUnit XML with 1 failed test
    failing_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="1" skipped="0" time="0.050">
    <testcase classname="tests.test_core" name="test_failed_case" time="0.050">
        <failure message="AssertionError: expected True but got False">assert False</failure>
    </testcase>
</testsuite>
"""

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/xml"},
        content=failing_xml,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["failed"] == 1

    # Verify confidence report was updated and score is reduced
    conf_response = client.get(
        f"/api/v1/analyses/{analysis_id}/confidence",
        headers=headers,
    )
    assert conf_response.status_code == 200
    conf_data = conf_response.json()["data"]
    assert conf_data["confidence_score"] < baseline_conf


def test_ingest_json_results() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/json"},
        json={"total": 5, "passed": 5, "failed": 0, "skipped": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total_tests"] == 5
    assert data["passed"] == 5
    assert data["failed"] == 0


def test_ingest_test_results_organization_authorization() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    different_org_headers = {"X-Radius-Organization-Id": str(uuid4())}
    response = client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**different_org_headers, "Content-Type": "application/json"},
        json={"total": 5, "passed": 5, "failed": 0, "skipped": 0},
    )

    assert response.status_code == 403


def test_get_test_run_results_endpoint() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    # Before ingestion: should be 404
    not_found_res = client.get(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers=headers,
    )
    assert not_found_res.status_code == 404

    # Ingest results
    client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/json"},
        json={"total": 8, "passed": 7, "failed": 1, "skipped": 0, "duration_ms": 450},
    )

    # After ingestion: should return 200 with result data
    res = client.get(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total_tests"] == 8
    assert data["passed"] == 7
    assert data["failed"] == 1
    assert data["duration_ms"] == 450

