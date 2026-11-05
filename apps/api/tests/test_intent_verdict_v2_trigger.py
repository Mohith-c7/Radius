"""Confirm / edit / reject of an intent criterion asks the worker to refresh verdict v2 (DEC-033).

Covers the trigger only (the outbox row); the worker recompute has its own tests.
Memory and SQL (SQLite) backends, real auth (legacy env keys plus managed keys).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from radius_shared.database.verdict_v2 import VerdictV2RequestRow
from radius_shared.verdict_v2_repository import SqlVerdictV2Repository
from radius_shared.verdict_v2_testing import make_bundle
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

PEPPER = "pepper-" + "x" * 40
BODY = (
    "## Acceptance Criteria\n"
    "- Users must be able to reset their password\n"
    "- Sessions should expire after 30 minutes\n"
)


class Env:
    def __init__(self, client: TestClient, orgs: list[str], keys: dict[str, str], engine) -> None:
        self.client = client
        self.org_a, self.org_b = orgs
        self.keys = keys
        self.engine = engine
        self.container = client.app.state.container
        self.analysis_id = ""

    def headers(self, org: str | None = None, key: str | None = None) -> dict[str, str]:
        org = org or self.org_a
        return {"X-Radius-Organization-Id": org, "X-Radius-API-Key": key or self.keys[org]}

    def make_key(self, scopes: list[str]) -> str:
        response = self.client.post(
            "/api/v1/api-keys",
            headers=self.headers(),
            json={"name": "k", "scopes": scopes},
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]["token"]

    def pending(self, org: str | None = None):
        org_id = UUID(org or self.org_a)
        analysis = UUID(self.analysis_id)
        if self.engine is None:
            return self.container.verdict_v2_repository.get_request(org_id, analysis)
        with Session(self.engine) as session:
            return SqlVerdictV2Repository(session).get_request(org_id, analysis)

    def store(self) -> None:
        bundle = make_bundle(self.analysis_id)
        if self.engine is None:
            self.container.verdict_v2_repository.save(
                UUID(self.org_a), UUID(self.analysis_id), bundle, mode="on"
            )
            return
        with Session(self.engine) as session:
            SqlVerdictV2Repository(session).save(
                UUID(self.org_a), UUID(self.analysis_id), bundle, mode="on"
            )
            session.commit()

    def criteria(self) -> list[dict]:
        response = self.client.get(
            f"/api/v1/analyses/{self.analysis_id}/intent", headers=self.headers()
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]["criteria"]

    def patch(self, criterion: str, body: dict, **kw):
        return self.client.patch(
            f"/api/v1/analyses/{self.analysis_id}/intent/criteria/{criterion}",
            headers=self.headers(**kw),
            json=body,
        )


def _build(monkeypatch, tmp_path, backend: str, flag: str | None) -> Env:
    orgs = [str(uuid4()), str(uuid4())]
    keys = {orgs[0]: "legacy-" + "a" * 24, orgs[1]: "legacy-" + "b" * 24}
    monkeypatch.setenv("RADIUS_ENV", "development")
    monkeypatch.setenv("API_KEYS", ",".join(f"{o}:{k}" for o, k in keys.items()))
    monkeypatch.setenv("RADIUS_API_KEY_PEPPER", PEPPER)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setenv("RADIUS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "false")
    monkeypatch.delenv("RADIUS_FEATURE_VERDICT_V2", raising=False)
    monkeypatch.setenv("RADIUS_FEATURE_INTENT_INGESTION", "true")
    if flag is not None:
        monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", flag)
    engine = None
    if backend == "sql":
        url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            for org in orgs:
                session.add(db_models.Organization(id=UUID(org), name=f"Org {org[:4]}"))
            session.commit()
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("STORAGE_BACKEND", "sql")
    get_api_settings.cache_clear()
    env = Env(TestClient(create_app()), orgs, keys, engine)
    repo = env.client.post(
        "/api/v1/repositories",
        headers=env.headers(),
        json={
            "organizationId": env.org_a,
            "repositoryId": int(uuid4().int % 10**9),
            "name": f"repo-{uuid4().hex[:6]}",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    )
    assert repo.status_code in (200, 201), repo.text
    started = env.client.post(
        "/api/v1/analyses",
        headers=env.headers(),
        json={
            "repositoryId": repo.json()["data"]["id"],
            "pullRequestId": str(uuid4()),
            "commitSha": "a" * 40,
        },
    )
    assert started.status_code == 202, started.text
    env.analysis_id = started.json()["data"]["id"]
    submitted = env.client.post(
        f"/api/v1/analyses/{env.analysis_id}/intent/sources",
        headers=env.headers(),
        json={"kind": "pr_body", "text": BODY},
    )
    assert submitted.status_code == 201, submitted.text
    return env


@pytest.fixture(params=["memory", "sql"])
def backend(request) -> str:
    return request.param


@pytest.fixture
def env(monkeypatch, tmp_path, backend) -> Env:
    return _build(monkeypatch, tmp_path, backend, "on")


def _states(env: Env) -> list[str]:
    return [c["state"] for c in env.criteria()]


def test_source_submit_does_not_enqueue(env: Env) -> None:
    assert env.pending() is None


def test_confirm_enqueues_one_debounced_request(env: Env) -> None:
    first = env.criteria()[0]["id"]
    before = datetime.now(UTC)

    response = env.patch(first, {"action": "confirm"})

    assert response.status_code == 200, response.text
    assert _states(env)[0] == "confirmed"
    pending = env.pending()
    assert pending is not None and pending.reason == "intent_changed"
    # trailing debounce: the worker may not claim it before a few seconds have passed
    available = pending.available_at
    available = available if available.tzinfo else available.replace(tzinfo=UTC)
    assert (available - before).total_seconds() > 1.0
    assert env.pending(env.org_b) is None


@pytest.mark.parametrize(
    ("action", "body", "state"),
    [
        ("reject", {"action": "reject"}, "rejected"),
        ("edit", {"action": "edit", "text": "Users must reset their password within a day"}, "edited"),
    ],
)
def test_reject_and_edit_enqueue(env: Env, action: str, body: dict, state: str) -> None:
    first = env.criteria()[0]["id"]

    assert env.patch(first, body).status_code == 200, action

    assert _states(env)[0] == state
    assert env.pending() is not None


def test_several_quick_changes_collapse_into_one_request(env: Env) -> None:
    ids = [c["id"] for c in env.criteria()]
    for criterion in ids:
        assert env.patch(criterion, {"action": "confirm"}).status_code == 200

    pending = env.pending()
    assert pending is not None and pending.attempts == 0
    if env.engine is not None:
        with Session(env.engine) as session:
            assert session.query(VerdictV2RequestRow).count() == 1


def test_illegal_transition_changes_nothing_and_enqueues_nothing(env: Env) -> None:
    first = env.criteria()[0]["id"]
    assert env.patch(first, {"action": "reject"}).status_code == 200
    # the first request exists; clear by checking a different org stays empty and the
    # illegal move is refused without touching the row
    pending_before = env.pending()
    response = env.patch(first, {"action": "confirm"})
    assert response.status_code == 409
    assert _states(env)[0] == "rejected"
    assert env.pending() == pending_before


def test_flag_off_confirm_works_and_enqueues_nothing(monkeypatch, tmp_path, backend) -> None:
    env = _build(monkeypatch, tmp_path, backend, None)
    first = env.criteria()[0]["id"]

    assert env.patch(first, {"action": "confirm"}).status_code == 200

    assert _states(env)[0] == "confirmed"
    assert env.pending() is None


def test_read_only_key_cannot_change_state_or_enqueue(env: Env) -> None:
    reader = env.make_key(["read"])
    first = env.criteria()[0]["id"]

    response = env.patch(first, {"action": "confirm"}, key=reader)

    assert response.status_code == 403
    assert _states(env)[0] == "proposed"
    assert env.pending() is None


def test_ci_upload_key_cannot_change_state_or_enqueue(env: Env) -> None:
    uploader = env.make_key(["ci-upload"])
    first = env.criteria()[0]["id"]

    assert env.patch(first, {"action": "confirm"}, key=uploader).status_code == 403

    assert _states(env)[0] == "proposed"
    assert env.pending() is None


@pytest.mark.parametrize("key", [None, "wrong-key-" + "z" * 20])
def test_unauthenticated_call_changes_nothing_and_enqueues_nothing(env: Env, key) -> None:
    first = env.criteria()[0]["id"]
    headers = {"X-Radius-Organization-Id": env.org_a}
    if key:
        headers["X-Radius-API-Key"] = key

    response = env.client.patch(
        f"/api/v1/analyses/{env.analysis_id}/intent/criteria/{first}",
        headers=headers,
        json={"action": "confirm"},
    )

    assert response.status_code in (401, 403)
    assert _states(env)[0] == "proposed"
    assert env.pending() is None


def test_other_organization_cannot_change_state_or_enqueue(env: Env) -> None:
    first = env.criteria()[0]["id"]

    response = env.patch(first, {"action": "confirm"}, org=env.org_b)

    assert response.status_code == 404
    assert _states(env)[0] == "proposed"
    assert env.pending() is None
    assert env.pending(env.org_b) is None


def test_request_body_cannot_carry_provenance(env: Env) -> None:
    first = env.criteria()[0]["id"]

    response = env.patch(first, {"action": "confirm", "provenance": "human_confirmed"})

    assert response.status_code == 422
    assert _states(env)[0] == "proposed"
    assert env.pending() is None


def test_enqueue_failure_never_breaks_the_confirm(monkeypatch, tmp_path) -> None:
    env = _build(monkeypatch, tmp_path, "memory", "on")

    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(env.container.verdict_v2_repository, "enqueue_request", boom)
    first = env.criteria()[0]["id"]

    response = env.patch(first, {"action": "confirm"})

    assert response.status_code == 200
    assert _states(env)[0] == "confirmed"


def test_verdict_endpoint_marks_the_verdict_stale_while_a_refresh_is_queued(env: Env) -> None:
    env.store()
    plain = env.client.get(
        f"/api/v1/analyses/{env.analysis_id}/verdict-v2", headers=env.headers()
    )
    assert plain.status_code == 200
    assert "refresh_pending" not in plain.json()["meta"]

    first = env.criteria()[0]["id"]
    assert env.patch(first, {"action": "confirm"}).status_code == 200

    stale = env.client.get(
        f"/api/v1/analyses/{env.analysis_id}/verdict-v2", headers=env.headers()
    )
    assert stale.status_code == 200
    assert stale.json()["meta"]["refresh_pending"] is True
    assert stale.json()["meta"]["refresh_reason"] == "intent_changed"
    # a cached 304 must not hide the marker
    again = env.client.get(
        f"/api/v1/analyses/{env.analysis_id}/verdict-v2",
        headers={**env.headers(), "If-None-Match": plain.headers["ETag"]},
    )
    assert again.status_code == 200
