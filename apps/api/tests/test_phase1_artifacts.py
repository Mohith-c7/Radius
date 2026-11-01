"""Phase 1 artifact API tests."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_confidence.domain import (
    AnalysisEvidence,
    CoveragePercent,
    ImpactEvidence,
)
from radius_confidence.domain import (
    TestEvidence as ConfidenceTestEvidence,
)
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_graph.domain import (
    DependencyGraph,
    GraphNode,
    GraphNodeId,
    GraphNodeType,
    GraphSnapshot,
)
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


def test_phase1_artifact_endpoints_return_graph_tests_and_confidence() -> None:
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": organization_id}
    repository = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": organization_id,
            "repositoryId": 303,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    )
    repository_id = repository.json()["data"]["id"]
    analysis = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": repository_id,
            "pullRequestId": str(uuid4()),
            "commitSha": "c" * 40,
        },
    )
    analysis_id = analysis.json()["data"]["id"]
    repository_uuid = UUID(repository_id)
    analysis_uuid = UUID(analysis_id)
    test_case = RadiusTestCase(
        id=uuid4(),
        name=RadiusTestName("test_core"),
        path=RadiusTestPath("tests/test_core.py"),
        framework=RadiusTestFramework.PYTEST,
    )
    app.state.container.graph_store.save_snapshot(
        GraphSnapshot(
            repository_id=repository_uuid,
            analysis_id=analysis_uuid,
            graph=DependencyGraph(
                nodes=(
                    GraphNode(
                        GraphNodeId("file:src/core.py"),
                        GraphNodeType.FILE,
                        "src/core.py",
                        "src/core.py",
                    ),
                )
            ),
        )
    )
    app.state.container.test_store.save_selection(
        RadiusTestSelection(
            analysis_id=analysis_uuid,
            selected_tests=(
                SelectedTest(test_case, RadiusTestSelectionReason.AFFECTED_FILE),
            ),
        )
    )
    app.state.container.confidence_service().generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_uuid,
            impact=ImpactEvidence(
                affected_files=1,
                affected_symbols=1,
                affected_modules=0,
                affected_tests=1,
                dependency_depth=0,
            ),
            tests=ConfidenceTestEvidence(
                total_tests=1,
                passed=1,
                failed=0,
                skipped=0,
                coverage_percent=CoveragePercent(90),
            ),
            analysis=AnalysisEvidence(changed_files=1, covered_files=("src/app.py",)),
        )
    )

    graph = client.get(f"/api/v1/analyses/{analysis_id}/graph", headers=headers)
    tests = client.get(f"/api/v1/analyses/{analysis_id}/tests", headers=headers)
    confidence = client.get(
        f"/api/v1/analyses/{analysis_id}/confidence",
        headers=headers,
    )

    assert graph.status_code == 200
    assert graph.json()["data"]["node_count"] == 1
    assert tests.status_code == 200
    assert tests.json()["data"]["selected_count"] == 1
    assert confidence.status_code == 200
    assert confidence.json()["data"]["risk_level"] == "low"
    assert confidence.json()["data"]["verification_status"] == "verified"


def test_missing_graph_artifact_uses_not_found_envelope() -> None:
    client = TestClient(create_app())
    headers = {"X-Radius-Organization-Id": str(uuid4())}

    response = client.get(f"/api/v1/analyses/{uuid4()}/graph", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
