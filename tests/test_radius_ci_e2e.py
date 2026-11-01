"""End-to-end: scripts/radius_ci.py against the real Radius API served by uvicorn.

The API runs in-process (memory storage) on a free localhost port, so the
script's real HTTP path (headers, lookup, polling, upload, verdict) is
exercised without any external network or GitHub.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_confidence.domain import AnalysisEvidence, ImpactEvidence
from radius_confidence.domain import TestEvidence as ConfidenceTestEvidence
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_repository.dto import UpsertPullRequestCommand
from radius_testing.domain import SelectedTest
from radius_testing.domain import TestCase as RadiusTestCase
from radius_testing.domain import TestFramework as RadiusTestFramework
from radius_testing.domain import TestName as RadiusTestName
from radius_testing.domain import TestPath as RadiusTestPath
from radius_testing.domain import TestSelection as RadiusTestSelection
from radius_testing.domain import TestSelectionReason as RadiusTestSelectionReason

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "radius_ci.py"
_spec = importlib.util.spec_from_file_location("radius_ci_e2e", _SCRIPT)
radius_ci = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = radius_ci
_spec.loader.exec_module(radius_ci)

HEAD = "e" * 40
API_KEY = "e2e-secret-api-key-0123456789"
SELECTED = ("tests/test_checkout.py", "tests/test_cart.py")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def radius(monkeypatch):
    org = str(uuid4())
    monkeypatch.setenv("API_KEYS", f"{org}:{API_KEY}")
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "false")
    get_api_settings.cache_clear()
    app = create_app()
    get_api_settings.cache_clear()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:  # pragma: no cover
            pytest.fail("uvicorn did not start")
        time.sleep(0.02)
    monkeypatch.setattr(radius_ci, "_sleep", lambda seconds: None)
    yield app, org, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def _seed_analysis(app, org: str) -> str:
    """Connect a repo, record PR #12, create the head analysis and its plan."""

    client = TestClient(app)
    headers = {"X-Radius-Organization-Id": org, "X-Radius-API-Key": API_KEY}
    repository_id = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": org,
            "repositoryId": 5150,
            "name": "shop",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/shop.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    container = app.state.container
    pull_request = container.repository_service().upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=UUID(repository_id),
            github_pr_number=12,
            title="Checkout",
            source_branch="feature",
            target_branch="main",
            author="octocat",
            status="open",
            opened_at=datetime.now(UTC),
        )
    )
    analysis_id = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": repository_id,
            "pullRequestId": str(pull_request.id),
            "commitSha": HEAD,
        },
    ).json()["data"]["id"]
    analysis_uuid = UUID(analysis_id)
    # What the worker would have produced: a plan and a not-yet-run report.
    container.test_store.save_selection(
        RadiusTestSelection(
            analysis_id=analysis_uuid,
            selected_tests=tuple(
                SelectedTest(
                    RadiusTestCase(
                        id=uuid4(),
                        name=RadiusTestName(path.rsplit("/", 1)[-1].removesuffix(".py")),
                        path=RadiusTestPath(path),
                        framework=RadiusTestFramework.PYTEST,
                    ),
                    RadiusTestSelectionReason.AFFECTED_FILE,
                )
                for path in SELECTED
            ),
        )
    )
    container.confidence_service().generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis_uuid,
            impact=ImpactEvidence(1, 1, 1, 2, 1),
            tests=ConfidenceTestEvidence(0, 0, 0, 0, run_outcome="not_run"),
            analysis=AnalysisEvidence(changed_files=1, covered_files=("shop/checkout.py",)),
        )
    )
    return analysis_id


def _junit(tmp_path: Path, name: str, *, fail: str | None = None) -> str:
    cases = []
    for path in SELECTED:
        module = path.removesuffix(".py").replace("/", ".")
        failure = '<failure message="boom"/>' if module == fail else ""
        cases.append(f'<testcase classname="{module}" name="test_it">{failure}</testcase>')
    report = tmp_path / name
    report.write_text(f'<testsuite name="pytest">{"".join(cases)}</testsuite>', encoding="utf-8")
    return str(report)


def _common(api: str, org: str) -> list[str]:
    return [
        "--api", api, "--org", org,
        "--repository", "acme/shop", "--pr", "12", "--commit", HEAD,
        "--poll-interval", "0", "--wait", "5",
    ]


def test_plan_then_upload_verifies_the_pull_request(radius, tmp_path, capsys, monkeypatch) -> None:
    app, org, api = radius
    monkeypatch.setenv("RADIUS_API_KEY", API_KEY)
    analysis_id = _seed_analysis(app, org)

    # Still pending: plan polls, then the "worker" completes the analysis.
    polls = []

    def complete_after_first_poll(seconds: float) -> None:
        polls.append(seconds)
        app.state.container.analysis_service().complete_analysis(UUID(analysis_id))

    monkeypatch.setattr(radius_ci, "_sleep", complete_after_first_poll)
    tests_file = tmp_path / "radius-tests.txt"
    plan_code = radius_ci.main(["plan", *_common(api, org), "--output", str(tests_file)])
    plan_out = capsys.readouterr()

    assert plan_code == 0, plan_out.err
    assert polls, "plan should have waited for the pending analysis"
    assert sorted(plan_out.out.split()) == sorted(SELECTED)
    assert sorted(tests_file.read_text().split()) == sorted(SELECTED)

    upload_code = radius_ci.main(
        ["upload", *_common(api, org), "--junit", _junit(tmp_path, "junit.xml"), "--require-verified"]
    )
    upload_out = capsys.readouterr()

    assert upload_code == 0, upload_out.err
    assert "Radius verdict: verified" in upload_out.out
    assert "Selected test files executed: 2/2." in upload_out.out
    assert API_KEY not in plan_out.out + plan_out.err + upload_out.out + upload_out.err


def test_failing_selected_test_exits_4(radius, tmp_path, capsys, monkeypatch) -> None:
    app, org, api = radius
    monkeypatch.setenv("RADIUS_API_KEY", API_KEY)
    analysis_id = _seed_analysis(app, org)
    app.state.container.analysis_service().complete_analysis(UUID(analysis_id))

    code = radius_ci.main(
        ["upload", *_common(api, org), "--junit", _junit(tmp_path, "j.xml", fail="tests.test_cart")]
    )
    out = capsys.readouterr()

    assert code == 4, out.err
    assert "Radius verdict: failed" in out.out


def test_wrong_api_key_is_rejected_with_actionable_message(radius, capsys, monkeypatch) -> None:
    app, org, api = radius
    _seed_analysis(app, org)
    monkeypatch.setenv("RADIUS_API_KEY", "not-the-key")

    code = radius_ci.main(["resolve", *_common(api, org)])
    out = capsys.readouterr()

    assert code == 1
    assert "HTTP 403" in out.err
    assert "RADIUS_API_KEY" in out.err
    assert "not-the-key" not in out.err + out.out
