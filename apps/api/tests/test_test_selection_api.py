"""Tests for Test Selection API routes."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_testing.domain import (
    SelectedTest,
)
from radius_testing.domain import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain import (
    TestFramework as RadiusTestFramework,
)
from radius_testing.domain import (
    TestName as RadiusTestName,
)
from radius_testing.domain import (
    TestPath as RadiusTestPath,
)
from radius_testing.domain import (
    TestSelection as RadiusTestSelection,
)
from radius_testing.domain import (
    TestSelectionReason as RadiusTestSelectionReason,
)


def _create_test_case(path: str) -> RadiusTestCase:
    return RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName(path.split("/")[-1]),
        path=RadiusTestPath(path),
        framework=RadiusTestFramework.PYTEST,
    )


def _setup_analysis(client: TestClient, headers: dict[str, str]) -> tuple[UUID, UUID]:
    org_id = headers["X-Radius-Organization-Id"]
    repo_res = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": org_id,
            "repositoryId": 501,
            "name": "test-repo",
            "owner": "radius-test",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/radius-test/test-repo.git",
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


def test_get_selected_tests_json_returns_optimization_metrics() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    t1 = _create_test_case("tests/test_auth.py")
    t2 = _create_test_case("tests/test_core.py")
    t3 = _create_test_case("tests/test_db.py")
    t4 = _create_test_case("tests/test_ui.py")
    t5 = _create_test_case("tests/test_worker.py")

    selection = RadiusTestSelection(
        analysis_id=analysis_id,
        selected_tests=(
            SelectedTest(t1, RadiusTestSelectionReason.CHANGED_FILE),
            SelectedTest(t2, RadiusTestSelectionReason.AFFECTED_FILE),
        ),
        skipped_tests=(t3, t4, t5),
        total_discovered_count=5,
    )
    app.state.container.test_store.save_selection(selection)

    response = client.get(f"/api/v1/analyses/{analysis_id}/tests", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]

    # Verify metrics fields (both snake_case canonical and camelCase compatible)
    selected_count = data.get("selectedCount", data.get("selected_count"))
    skipped_count = data.get("skippedCount", data.get("skipped_count"))
    time_saved_percent = data.get("timeSavedPercent", data.get("time_saved_percent"))
    cli_args = data.get("cliArgs", data.get("cli_args"))

    assert selected_count == 2
    assert skipped_count == 3
    assert time_saved_percent == 60.0
    assert cli_args == "tests/test_auth.py tests/test_core.py"

    assert data["selected_count"] == 2
    assert data["skipped_count"] == 3
    assert data["total_count"] == 5
    assert data["time_saved_percent"] == 60.0
    assert data["cli_args"] == "tests/test_auth.py tests/test_core.py"
    assert len(data["selected_tests"]) == 2
    assert len(data["skipped_tests"]) == 3


def test_get_selected_tests_cli_format_returns_plaintext() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    t1 = _create_test_case("tests/test_auth.py")
    t2 = _create_test_case("tests/test_core.py")
    t3 = _create_test_case("tests/test_worker.py")

    selection = RadiusTestSelection(
        analysis_id=analysis_id,
        selected_tests=(
            SelectedTest(t1, RadiusTestSelectionReason.CHANGED_FILE),
            SelectedTest(t2, RadiusTestSelectionReason.AFFECTED_FILE),
        ),
        skipped_tests=(t3,),
        total_discovered_count=3,
    )
    app.state.container.test_store.save_selection(selection)

    response = client.get(
        f"/api/v1/analyses/{analysis_id}/tests?format=cli",
        headers=headers,
    )

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert response.text == "tests/test_auth.py tests/test_core.py"


def test_get_selected_tests_cli_format_empty_selection() -> None:
    app = create_app()
    client = TestClient(app)
    org_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": org_id}
    _, analysis_id = _setup_analysis(client, headers)

    t1 = _create_test_case("tests/test_auth.py")
    selection = RadiusTestSelection(
        analysis_id=analysis_id,
        selected_tests=(),
        skipped_tests=(t1,),
        total_discovered_count=1,
    )
    app.state.container.test_store.save_selection(selection)

    response = client.get(
        f"/api/v1/analyses/{analysis_id}/tests?format=cli",
        headers=headers,
    )

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert response.text == ""
