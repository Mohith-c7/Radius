"""Runtime coverage API integration tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from radius_api.main import create_app


def test_coverage_api_ingests_lcov_and_uses_requested_analysis_id() -> None:
    app = create_app()
    client = TestClient(app)
    organization_id = str(uuid4())
    headers = {"X-Radius-Organization-Id": organization_id}
    repository = client.post("/api/v1/repositories", headers=headers, json={"organizationId": organization_id, "repositoryId": 99, "name": "radius", "owner": "acme", "defaultBranch": "main", "cloneUrl": "https://example.test/radius.git", "visibility": "private"})
    analysis = client.post("/api/v1/analyses", headers=headers, json={"repositoryId": repository.json()["data"]["id"], "pullRequestId": str(uuid4()), "commitSha": "a" * 40})
    analysis_id = analysis.json()["data"]["id"]
    payload = {"framework": "pytest", "report_format": "lcov", "report": "TN:tests/test_core.py\nSF:src/core.py\nFN:1,calculate\nFNDA:1,calculate\nDA:1,1\nend_of_record\n"}

    response = client.post("/api/v1/coverage", headers={**headers, "X-Analysis-Id": analysis_id}, json=payload)
    summary = client.get(f"/api/v1/coverage/analysis/{analysis_id}", headers=headers)
    report = client.get(f"/api/v1/coverage/analysis/{analysis_id}/report", headers=headers)
    artifact = client.get(f"/api/v1/coverage/artifact?analysis_id={analysis_id}&file_path=src/core.py", headers=headers)
    symbol = client.get(f"/api/v1/coverage/symbol?analysis_id={analysis_id}&file_path=src/core.py&symbol=calculate", headers=headers)

    assert response.status_code == 202
    assert summary.status_code == 200
    assert summary.json()["data"]["coverage_percent"] == 100.0
    assert report.status_code == 200
    assert artifact.status_code == 200
    assert symbol.status_code == 200
