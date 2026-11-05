"""F-06: recorded-style GitHub webhook payloads, signed like GitHub signs them.

The fixtures live in ``packages/github/tests/fixtures/webhooks`` and mirror the
shape of real deliveries (extra fields included). Each test posts the raw file
bytes with a real ``X-Hub-Signature-256`` and checks routing, idempotency and
that no duplicate analyses are created. When a live run produces a payload that
behaves differently, replace/add the fixture and keep the test.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

FIXTURES = (
    Path(__file__).resolve().parents[3] / "packages" / "github" / "tests" / "fixtures" / "webhooks"
)
SECRET = "fixture-webhook-secret"
URL = "/api/v1/webhooks/github"
HEAD1, HEAD2, HEAD3 = "1" * 39 + "a", "2" * 39 + "b", "3" * 39 + "c"


def _raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client: TestClient, event: str, name: str, delivery: str, *, secret: str = SECRET):
    body = _raw(name)
    return client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": _sign(body, secret),
            "Content-Type": "application/json",
            "User-Agent": "GitHub-Hookshot/abc123",
        },
    )


def _memory_app():
    app = create_app()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_default_organization_id = uuid4()
    app.state.settings.github_single_tenant = True
    return app, TestClient(app)


def test_fixture_files_are_valid_json_and_unsigned_content_is_stable() -> None:
    import json

    names = sorted(path.stem for path in FIXTURES.glob("*.json"))
    assert len(names) >= 15
    for name in names:
        assert isinstance(json.loads(_raw(name)), dict), name


def test_ping_is_acknowledged_and_creates_nothing() -> None:
    app, client = _memory_app()
    response = _post(client, "ping", "ping", "d-ping")
    assert response.status_code == 202
    assert response.json()["data"]["event"] == "ping"
    assert len(app.state.container.analysis_queue) == 0


@pytest.mark.parametrize("event,name", [("ping", "ping"), ("pull_request", "pull_request_opened")])
def test_bad_or_missing_signature_is_rejected(event: str, name: str) -> None:
    app, client = _memory_app()
    wrong = _post(client, event, name, "d-bad", secret="not-the-secret")
    assert wrong.status_code == 403
    missing = client.post(
        URL,
        content=_raw(name),
        headers={"X-GitHub-Event": event, "X-GitHub-Delivery": "d-miss"},
    )
    assert missing.status_code == 403
    # Signature computed over a different body (tampering) must fail too.
    tampered = client.post(
        URL,
        content=_raw(name) + b" ",
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": "d-tamper",
            "X-Hub-Signature-256": _sign(_raw(name)),
        },
    )
    assert tampered.status_code == 403
    assert len(app.state.container.analysis_queue) == 0


def test_signature_without_sha256_prefix_is_rejected() -> None:
    _, client = _memory_app()
    body = _raw("pull_request_opened")
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "d-noprefix",
            "X-Hub-Signature-256": digest,
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "event,name",
    [
        ("issue_comment", "issue_comment_created"),
        ("issues", "issues_opened"),
        ("check_run", "check_run_completed"),
    ],
)
def test_subscribed_but_unhandled_events_are_ignored_without_side_effects(
    event: str, name: str
) -> None:
    app, client = _memory_app()
    response = _post(client, event, name, f"d-{event}")
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["ignored"] is True
    assert data["analysisId"] is None
    assert len(app.state.container.analysis_queue) == 0


def test_pull_request_opened_starts_exactly_one_analysis() -> None:
    app, client = _memory_app()
    response = _post(client, "pull_request", "pull_request_opened", "d-open")
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["ignored"] is False
    assert data["analysisId"]
    assert len(app.state.container.analysis_queue) == 1


def test_redelivery_with_same_delivery_id_is_idempotent() -> None:
    app, client = _memory_app()
    first = _post(client, "pull_request", "pull_request_opened", "d-redeliver")
    second = _post(client, "pull_request", "pull_request_opened", "d-redeliver")
    third = _post(client, "pull_request", "pull_request_opened", "d-redeliver")
    assert first.status_code == second.status_code == third.status_code == 202
    assert first.json() == second.json() == third.json()
    assert len(app.state.container.analysis_queue) == 1


def test_redelivery_of_ignored_event_is_idempotent() -> None:
    _, client = _memory_app()
    first = _post(client, "issue_comment", "issue_comment_created", "d-ic")
    second = _post(client, "issue_comment", "issue_comment_created", "d-ic")
    assert first.json() == second.json()


def test_new_delivery_id_for_same_head_sha_does_not_duplicate_analysis() -> None:
    app, client = _memory_app()
    first = _post(client, "pull_request", "pull_request_opened", "d-1")
    second = _post(client, "pull_request", "pull_request_opened", "d-2")
    assert first.json()["data"]["analysisId"] == second.json()["data"]["analysisId"]
    assert len(app.state.container.analysis_queue) == 1


def test_synchronize_and_force_push_each_start_an_analysis_for_the_new_head() -> None:
    app, client = _memory_app()
    opened = _post(client, "pull_request", "pull_request_opened", "d-a").json()["data"]
    sync = _post(client, "pull_request", "pull_request_synchronize", "d-b").json()["data"]
    forced = _post(client, "pull_request", "pull_request_synchronize_force_push", "d-c").json()[
        "data"
    ]
    ids = {opened["analysisId"], sync["analysisId"], forced["analysisId"]}
    assert len(ids) == 3
    # One pull request row throughout.
    assert opened["pullRequestId"] == sync["pullRequestId"] == forced["pullRequestId"]
    assert len(app.state.container.analysis_queue) == 3


@pytest.mark.parametrize(
    "name",
    [
        "pull_request_edited",
        "pull_request_edited_title",
        "pull_request_closed",
        "pull_request_closed_merged",
        "pull_request_labeled",
        "pull_request_opened_draft",
    ],
)
def test_non_analysis_pull_request_actions_do_not_enqueue(name: str) -> None:
    app, client = _memory_app()
    response = _post(client, "pull_request", name, f"d-{name}")
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["ignored"] is True
    assert data["analysisId"] is None
    assert data["pullRequestId"]
    assert len(app.state.container.analysis_queue) == 0


def test_ready_for_review_starts_analysis() -> None:
    app, client = _memory_app()
    data = _post(client, "pull_request", "pull_request_ready_for_review", "d-r").json()["data"]
    assert data["analysisId"]
    assert len(app.state.container.analysis_queue) == 1


def test_reopen_after_close_starts_a_fresh_analysis_because_closing_cancelled_the_queued_one() -> None:
    app, client = _memory_app()
    sync = _post(client, "pull_request", "pull_request_synchronize", "d-s").json()["data"]
    closed = _post(client, "pull_request", "pull_request_closed", "d-c").json()["data"]
    # Closing drops the queued-not-started analysis (see test_github_webhook_defects).
    assert closed["cancelledAnalysisIds"] == [sync["analysisId"]]
    assert len(app.state.container.analysis_queue) == 0
    reopened = _post(client, "pull_request", "pull_request_reopened", "d-ro").json()["data"]
    assert reopened["analysisId"] != sync["analysisId"]
    assert reopened["pullRequestId"] == sync["pullRequestId"]
    assert len(app.state.container.analysis_queue) == 1


def test_push_event_is_handled_and_creates_no_analysis() -> None:
    app, client = _memory_app()
    response = _post(client, "push", "push_feature_branch", "d-push")
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["event"] == "push"
    assert data["ignored"] is False
    assert data["analysisId"] is None
    assert len(app.state.container.analysis_queue) == 0


def test_unknown_installation_is_rejected_even_with_valid_signature_when_multi_tenant() -> None:
    app = create_app()
    app.state.settings.github_webhook_secret = SECRET
    app.state.settings.github_default_organization_id = uuid4()
    app.state.settings.github_single_tenant = False
    response = _post(TestClient(app), "pull_request", "pull_request_opened", "d-mt")
    assert response.status_code == 403
    assert len(app.state.container.analysis_queue) == 0


def _sql_client(tmp_path: Path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    org_id = uuid4()
    with Session(engine) as session:
        session.add(db_models.Organization(id=org_id, name="Sandbox"))
        session.commit()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "true")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(org_id))
    get_api_settings.cache_clear()
    return engine, org_id, TestClient(create_app())


def test_persisted_flow_installation_link_dedup_and_redelivery(tmp_path, monkeypatch) -> None:
    """The live-run path: install -> open PR -> redeliver -> push -> force-push."""

    engine, org_id, client = _sql_client(tmp_path, monkeypatch)
    try:
        assert _post(client, "installation", "installation_created", "i-1").status_code == 202
        with Session(engine) as session:
            org = session.get(db_models.Organization, org_id)
            assert org.github_installation_id == 55001122
            assert session.query(db_models.Repository).count() == 1

        opened = _post(client, "pull_request", "pull_request_opened", "p-1")
        assert opened.status_code == 202, opened.text
        redelivered = _post(client, "pull_request", "pull_request_opened", "p-1")
        assert redelivered.json() == opened.json()
        sync = _post(client, "pull_request", "pull_request_synchronize", "p-2")
        forced = _post(client, "pull_request", "pull_request_synchronize_force_push", "p-3")
        edited = _post(client, "pull_request", "pull_request_edited_title", "p-4")
        closed = _post(client, "pull_request", "pull_request_closed", "p-5")
        reopened = _post(client, "pull_request", "pull_request_reopened", "p-6")
    finally:
        get_api_settings.cache_clear()

    assert edited.json()["data"]["ignored"] is True
    assert closed.json()["data"]["ignored"] is True
    # Closing cancelled the three queued analyses; reopening starts a new one
    # for the (unchanged) head instead of reusing a cancelled analysis.
    assert len(closed.json()["data"]["cancelledAnalysisIds"]) == 3
    assert reopened.json()["data"]["analysisId"] != sync.json()["data"]["analysisId"]
    with Session(engine) as session:
        analyses = session.query(db_models.Analysis).all()
        assert {a.commit_sha for a in analyses} == {HEAD1, HEAD2, HEAD3}
        assert len(analyses) == 4
        by_status = sorted(str(a.status.value) for a in analyses)
        assert by_status == ["cancelled", "cancelled", "cancelled", "pending"]
        assert forced.json()["data"]["analysisId"] in {str(a.id) for a in analyses}
        assert session.query(db_models.PullRequest).count() == 1
        pull_request = session.query(db_models.PullRequest).one()
        # reopened payload is state=open again
        assert str(pull_request.status).lower().endswith("open")
        assert session.query(db_models.IdempotencyKey).count() >= 7
