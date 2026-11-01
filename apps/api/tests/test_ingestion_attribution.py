"""CI results only verify an analysis when they cover the selected tests."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app
from radius_confidence.domain import AnalysisEvidence, ImpactEvidence
from radius_confidence.domain import TestEvidence as ConfidenceTestEvidence
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_testing.domain import SelectedTest
from radius_testing.domain import TestCase as RadiusTestCase
from radius_testing.domain import TestFramework as RadiusTestFramework
from radius_testing.domain import TestName as RadiusTestName
from radius_testing.domain import TestPath as RadiusTestPath
from radius_testing.domain import TestSelection as RadiusTestSelection
from radius_testing.domain import TestSelectionReason as RadiusTestSelectionReason

HEAD = "a" * 40


def _junit(classname: str) -> str:
    return (
        '<testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0">'
        f'<testcase classname="{classname}" name="test_one"/>'
        f'<testcase classname="{classname}" name="test_two"/>'
        "</testsuite>"
    )


def _mapped_analysis():
    app = create_app()
    client = TestClient(app)
    org = str(uuid4())
    headers = {"X-Radius-Organization-Id": org}
    repo = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": org,
            "repositoryId": 404,
            "name": "shop",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/shop.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    analysis_id = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repo, "pullRequestId": str(uuid4()), "commitSha": HEAD},
    ).json()["data"]["id"]
    analysis_uuid = UUID(analysis_id)
    container = app.state.container
    container.test_store.save_selection(
        RadiusTestSelection(
            analysis_id=analysis_uuid,
            selected_tests=(
                SelectedTest(
                    RadiusTestCase(
                        id=uuid4(),
                        name=RadiusTestName("test_checkout"),
                        path=RadiusTestPath("tests/test_checkout.py"),
                        framework=RadiusTestFramework.PYTEST,
                    ),
                    RadiusTestSelectionReason.AFFECTED_FILE,
                ),
            ),
        )
    )
    # The worker mapped the only changed file to the selected test but did not run it.
    container.confidence_service().generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_uuid,
            impact=ImpactEvidence(1, 1, 1, 1, 1),
            tests=ConfidenceTestEvidence(0, 0, 0, 0, run_outcome="not_run"),
            analysis=AnalysisEvidence(changed_files=1, covered_files=("shop/pricing.py",)),
        )
    )
    return client, headers, analysis_id


def _upload(client, headers, analysis_id, body, **params):
    return client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        headers={**headers, "Content-Type": "application/xml"},
        params=params,
        content=body,
    )


def _confidence(client, headers, analysis_id):
    return client.get(f"/api/v1/analyses/{analysis_id}/confidence", headers=headers).json()[
        "data"
    ]


def test_unrelated_passing_results_cannot_verify() -> None:
    client, headers, analysis_id = _mapped_analysis()

    assert _upload(client, headers, analysis_id, _junit("tests.test_unrelated")).status_code == 200

    report = _confidence(client, headers, analysis_id)
    assert report["verification_status"] == "insufficient_evidence"
    assert report["confidence_score"] <= 69
    assert any(item["message"] == "tests/test_checkout.py" for item in report["evidence"])


def test_results_covering_selected_tests_verify() -> None:
    client, headers, analysis_id = _mapped_analysis()

    response = _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD
    )

    assert response.status_code == 200
    assert _confidence(client, headers, analysis_id)["verification_status"] == "verified"


def test_results_for_another_commit_are_rejected() -> None:
    client, headers, analysis_id = _mapped_analysis()

    response = _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha="b" * 40
    )

    assert response.status_code == 409
    assert _confidence(client, headers, analysis_id)["verification_status"] == "insufficient_evidence"
