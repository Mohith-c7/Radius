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


def _mapped_analysis(
    selected: tuple[str, ...] = ("tests/test_checkout.py",),
    context: dict | None = None,
    complete: bool = True,
):
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
    pull_request = str(uuid4())
    analysis_id = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repo, "pullRequestId": pull_request, "commitSha": HEAD},
    ).json()["data"]["id"]
    if context is not None:
        context.update(repo=repo, pull_request=pull_request)
    analysis_uuid = UUID(analysis_id)
    container = app.state.container
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
                for path in selected
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
    if complete:
        # Uploads are only accepted once the worker finished the analysis.
        client.app.state.container.analysis_service().complete_analysis(analysis_uuid)
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

    assert _upload(client, headers, analysis_id, _junit("tests.test_unrelated"), commit_sha=HEAD).status_code == 200

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


def test_upload_without_commit_is_rejected_and_cannot_verify() -> None:
    client, headers, analysis_id = _mapped_analysis()

    response = _upload(client, headers, analysis_id, _junit("tests.test_checkout"))

    assert response.status_code == 422
    assert "commit_sha" in response.text
    assert _confidence(client, headers, analysis_id)["verification_status"] == "insufficient_evidence"


def test_malformed_or_empty_report_is_rejected_without_changing_verdict() -> None:
    client, headers, analysis_id = _mapped_analysis()
    malformed = (
        "",
        "   ",
        "<testsuite><testcase",
        "<html><body>not a report</body></html>",
        '{"total": "many"}',
        '{"total": -3, "failed": 0}',
        "[1, 2]",
        "not xml or json",
        '<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaa">]><testsuite>&a;</testsuite>',
    )

    for body in malformed:
        response = _upload(client, headers, analysis_id, body, commit_sha=HEAD)
        assert response.status_code == 422, body
    assert _confidence(client, headers, analysis_id)["verification_status"] == "insufficient_evidence"

    # After a valid verifying upload, a broken upload must not change anything.
    assert _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD
    ).status_code == 200
    for body in malformed:
        assert _upload(client, headers, analysis_id, body, commit_sha=HEAD).status_code == 422
    assert _confidence(client, headers, analysis_id)["verification_status"] == "verified"
    stored = client.get(f"/api/v1/analyses/{analysis_id}/tests/results", headers=headers)
    assert stored.json()["data"]["total_tests"] == 2


def test_upload_for_failed_or_cancelled_analysis_is_rejected() -> None:
    for action in ("fail_analysis", "cancel_analysis"):
        client, headers, analysis_id = _mapped_analysis(complete=False)
        service = client.app.state.container.analysis_service()
        getattr(service, action)(UUID(analysis_id))

        response = _upload(client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD)

        assert response.status_code == 409, action
        assert (
            _confidence(client, headers, analysis_id)["verification_status"]
            == "insufficient_evidence"
        )


def _cases_xml(*cases: tuple[str, str, str]) -> str:
    """Build JUnit XML from (classname, name, outcome) triples."""

    body = []
    failures = sum(1 for case in cases if case[2] == "failed")
    skipped = sum(1 for case in cases if case[2] == "skipped")
    for classname, name, outcome in cases:
        inner = {
            "failed": '<failure message="boom">assert False</failure>',
            "skipped": "<skipped/>",
        }.get(outcome, "")
        body.append(f'<testcase classname="{classname}" name="{name}">{inner}</testcase>')
    return (
        f'<testsuite name="pytest" tests="{len(cases)}" failures="{failures}" '
        f'errors="0" skipped="{skipped}">{"".join(body)}</testsuite>'
    )


def _labels(report: dict) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    for item in report["evidence"]:
        labels.setdefault(item["label"], set()).add(item["message"])
    return labels


def test_later_passing_shard_cannot_erase_earlier_failure() -> None:
    client, headers, analysis_id = _mapped_analysis(
        ("tests/test_checkout.py", "tests/test_cart.py")
    )

    first = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(("tests.test_checkout", "test_total", "failed")),
        commit_sha=HEAD,
    )
    second = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(
            ("tests.test_cart", "test_add", "passed"),
            ("tests.test_checkout", "test_other", "passed"),
        ),
        commit_sha=HEAD,
    )

    assert first.status_code == second.status_code == 200
    data = second.json()["data"]
    assert data["upload_count"] == 2
    assert data["failed"] == 1
    assert data["status"] == "failed"
    assert data["upload"]["failed"] == 0
    assert data["verification_status"] == "failed"
    assert _confidence(client, headers, analysis_id)["verification_status"] == "failed"
    stored = client.get(f"/api/v1/analyses/{analysis_id}/tests/results", headers=headers)
    assert stored.json()["data"]["failed"] == 1


def test_sharded_uploads_union_executed_cases_to_verify() -> None:
    client, headers, analysis_id = _mapped_analysis(
        ("tests/test_checkout.py", "tests/test_cart.py")
    )

    shard_one = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(("tests.test_checkout", "test_total", "passed")),
        commit_sha=HEAD,
    ).json()["data"]
    assert shard_one["verification_status"] == "insufficient_evidence"
    assert shard_one["selected_tests"]["not_reported"] == ["tests/test_cart.py"]

    shard_two = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(("tests.test_cart", "test_add", "passed")),
        commit_sha=HEAD,
    ).json()["data"]

    assert shard_two["upload_count"] == 2
    assert shard_two["total_tests"] == 2
    assert shard_two["selected_tests"]["executed_count"] == 2
    assert shard_two["verification_status"] == "verified"


def test_exact_replay_is_idempotent_and_not_double_counted() -> None:
    client, headers, analysis_id = _mapped_analysis()
    body = _junit("tests.test_checkout")

    first = _upload(client, headers, analysis_id, body, commit_sha=HEAD).json()["data"]
    replay = _upload(client, headers, analysis_id, body, commit_sha=HEAD).json()["data"]

    assert first["upload"]["duplicate"] is False
    assert replay["upload"]["duplicate"] is True
    assert replay["upload"]["id"] == first["upload"]["id"]
    assert replay["upload_count"] == 1
    assert replay["total_tests"] == first["total_tests"] == 2
    assert replay["verification_status"] == "verified"


def test_results_for_superseded_analysis_are_stale() -> None:
    context: dict = {}
    client, headers, analysis_id = _mapped_analysis(context=context)
    newer = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={
            "repositoryId": context["repo"],
            "pullRequestId": context["pull_request"],
            "commitSha": "b" * 40,
        },
    ).json()["data"]["id"]
    assert newer != analysis_id

    response = _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD
    )

    assert response.status_code == 409
    assert "stale" in response.text
    assert newer in response.text
    assert _confidence(client, headers, analysis_id)["verification_status"] == "insufficient_evidence"
    assert (
        client.get(f"/api/v1/analyses/{analysis_id}/tests/results", headers=headers).status_code
        == 404
    )


def test_ingestion_distinguishes_selected_executed_skipped_and_not_reported() -> None:
    client, headers, analysis_id = _mapped_analysis(
        ("tests/test_checkout.py", "tests/test_cart.py", "tests/test_orders.py")
    )

    data = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(
            ("tests.test_checkout", "test_total", "passed"),
            ("tests.test_cart", "test_add", "skipped"),
        ),
        commit_sha=HEAD,
    ).json()["data"]

    selected = data["selected_tests"]
    assert selected["selected_count"] == 3
    assert selected["executed_count"] == 1
    assert selected["passed_count"] == 1
    assert selected["failed_count"] == 0
    assert selected["skipped_count"] == 1
    assert selected["not_reported_count"] == 1
    assert selected["executed"] == ["tests/test_checkout.py"]
    assert selected["skipped"] == ["tests/test_cart.py"]
    assert selected["not_reported"] == ["tests/test_orders.py"]
    assert data["verification_status"] == "insufficient_evidence"

    labels = _labels(_confidence(client, headers, analysis_id))
    assert labels["selected_test_executed"] == {"tests/test_checkout.py"}
    assert labels["selected_test_only_skipped"] == {"tests/test_cart.py"}
    assert labels["selected_test_not_in_results"] == {"tests/test_orders.py"}
    assert "selected_test_files" in labels


def test_aggregate_only_report_is_not_evidence_for_selected_tests() -> None:
    client, headers, analysis_id = _mapped_analysis()

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/tests/results",
        params={"commit_sha": HEAD},
        headers=headers,
        json={"total": 50, "passed": 50, "failed": 0, "skipped": 0},
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["selected_tests"]["executed_count"] == 0
    assert data["selected_tests"]["not_reported"] == ["tests/test_checkout.py"]
    assert data["verification_status"] == "insufficient_evidence"


def test_results_without_selected_tests_cannot_verify_mapped_changes() -> None:
    client, headers, analysis_id = _mapped_analysis(selected=())

    data = _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD
    ).json()["data"]

    assert data["selected_tests"]["selected_count"] == 0
    assert data["verification_status"] == "insufficient_evidence"
    report = _confidence(client, headers, analysis_id)
    assert any("No selected test files" in gap for gap in _labels(report)["verdict_gap"])


def test_contradictory_results_count_as_failed_never_passed() -> None:
    client, headers, analysis_id = _mapped_analysis()

    _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(("tests.test_checkout", "test_total", "failed")),
        commit_sha=HEAD,
    )
    retry = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(("tests.test_checkout", "test_total", "passed")),
        commit_sha=HEAD,
    ).json()["data"]

    assert retry["contradictory_cases"] == ["tests.test_checkout::test_total"]
    assert retry["failed"] >= 1
    assert retry["selected_tests"]["failed"] == ["tests/test_checkout.py"]
    assert retry["verification_status"] == "failed"
    labels = _labels(_confidence(client, headers, analysis_id))
    assert "contradictory_test_result" in labels
    assert labels["selected_test_failed"] == {"tests/test_checkout.py"}


def test_contradiction_within_one_report_counts_as_failed() -> None:
    client, headers, analysis_id = _mapped_analysis()

    data = _upload(
        client,
        headers,
        analysis_id,
        _cases_xml(
            ("tests.test_checkout", "test_total", "passed"),
            ("tests.test_checkout", "test_total", "failed"),
        ),
        commit_sha=HEAD,
    ).json()["data"]

    assert data["verification_status"] == "failed"


def test_upload_before_analysis_completes_is_rejected() -> None:
    """The worker's own report must not later drop CI evidence (incl. failures)."""

    for action in (None, "mark_running"):
        client, headers, analysis_id = _mapped_analysis(complete=False)
        if action:
            getattr(client.app.state.container.analysis_service(), action)(UUID(analysis_id))

        response = _upload(
            client,
            headers,
            analysis_id,
            _cases_xml(("tests.test_checkout", "test_one", "failed")),
            commit_sha=HEAD,
        )

        assert response.status_code == 409, action
        assert "wait until it is completed" in response.text


def test_oversized_report_is_rejected_without_storing(monkeypatch) -> None:
    from radius_api.routes import tests as tests_route

    monkeypatch.setattr(tests_route, "MAX_REPORT_BYTES", 64)
    client, headers, analysis_id = _mapped_analysis()

    response = _upload(client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD)

    assert response.status_code == 413
    assert client.app.state.container.testing_service().count_result_uploads(UUID(analysis_id)) == 0


def test_upload_count_per_analysis_is_bounded(monkeypatch) -> None:
    from radius_api.routes import tests as tests_route

    monkeypatch.setattr(tests_route, "MAX_UPLOADS_PER_ANALYSIS", 1)
    client, headers, analysis_id = _mapped_analysis()

    first = _upload(client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD)
    second = _upload(client, headers, analysis_id, _junit("tests.test_other"), commit_sha=HEAD)

    assert first.status_code == 200
    assert second.status_code == 409


def test_stale_check_ignores_analyses_of_other_repositories() -> None:
    """Another tenant reusing a pull_request_id must not make uploads stale."""

    context: dict = {}
    client, headers, analysis_id = _mapped_analysis(context=context)
    other_org = str(uuid4())
    other_headers = {"X-Radius-Organization-Id": other_org}
    other_repo = client.post(
        "/api/v1/repositories",
        headers=other_headers,
        json={
            "organizationId": other_org,
            "repositoryId": 999,
            "name": "evil",
            "owner": "mallory",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/mallory/evil.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    foreign = client.post(
        "/api/v1/analyses",
        headers=other_headers,
        json={
            "repositoryId": other_repo,
            "pullRequestId": context["pull_request"],
            "commitSha": "b" * 40,
        },
    ).json()["data"]["id"]

    response = _upload(
        client, headers, analysis_id, _junit("tests.test_checkout"), commit_sha=HEAD
    )

    assert response.status_code == 200
    assert foreign not in response.text
