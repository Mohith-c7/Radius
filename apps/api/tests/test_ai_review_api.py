"""GET /analyses/{id}/ai-review (DEC-042): advisory payload, 404s, tenant isolation;
memory and SQL backends."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.ai_review import SqlAiReviewRepository, StoredAiReview
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

REVIEW = {
    "summary": "Adds retries to the uploader.",
    "risks": [{"text": "Retries may duplicate uploads.", "files": ["src/upload.py"]}],
    "tests": [],
    "missing_evidence": [{"text": "No CI results.", "files": []}],
    "next_steps": [],
    "notes": {"dropped": ["risks:verdict_claim"], "injection_flags": [], "diff_truncated": False},
}


class Env:
    def __init__(self, client: TestClient, orgs: list[str], engine=None) -> None:
        self.client = client
        self.org_a, self.org_b = orgs
        self.engine = engine
        self.container = client.app.state.container

    def headers(self, org: str | None = None) -> dict[str, str]:
        return {"X-Radius-Organization-Id": org or self.org_a}

    def analysis(self, org: str | None = None) -> str:
        org = org or self.org_a
        repo = self.client.post(
            "/api/v1/repositories",
            headers=self.headers(org),
            json={
                "organizationId": org,
                "repositoryId": int(uuid4().int % 10**9),
                "name": f"repo-{uuid4().hex[:6]}",
                "owner": "acme",
                "defaultBranch": "main",
                "cloneUrl": "https://github.com/acme/radius.git",
                "visibility": "private",
            },
        )
        started = self.client.post(
            "/api/v1/analyses",
            headers=self.headers(org),
            json={"repositoryId": repo.json()["data"]["id"], "pullRequestId": str(uuid4()), "commitSha": "a" * 40},
        )
        assert started.status_code == 202, started.text
        return started.json()["data"]["id"]

    def store(self, org: str, analysis: str, status: str = "ok") -> None:
        stored = StoredAiReview(
            organization_id=UUID(org),
            analysis_id=UUID(analysis),
            status=status,
            reason_code=None if status == "ok" else "provider_rate_limited",
            provider="openai_compatible",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            prompt_version="ai-review-v1",
            review=REVIEW if status == "ok" else None,
            created_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        )
        if self.engine is None:
            self.container.ai_review_repository.save(stored)
            return
        with Session(self.engine) as session:
            SqlAiReviewRepository(session).save(stored)
            session.commit()

    def get(self, analysis: str, org: str | None = None):
        return self.client.get(f"/api/v1/analyses/{analysis}/ai-review", headers=self.headers(org))


@pytest.fixture(params=["memory", "sql"])
def env(request, monkeypatch, tmp_path) -> Env:
    orgs = [str(uuid4()), str(uuid4())]
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    engine = None
    if request.param == "sql":
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
    return Env(TestClient(create_app()), orgs, engine)


def test_stored_review_is_served_as_advisory(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis)
    response = env.get(analysis)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["advisory"] is True and data["ai_generated"] is True
    assert "advisory" in data["label"] and data["status"] == "ok"
    assert data["risks"] == REVIEW["risks"] and data["summary"] == REVIEW["summary"]
    assert data["notes"]["dropped"] == ["risks:verdict_claim"]
    assert response.headers["cache-control"] == "private, no-cache"
    # No verdict, score or conclusion field exists in the payload.
    assert not {"verdict", "score", "conclusion", "verification_status"} & set(data)


def test_unavailable_review_has_a_reason_and_no_content(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, status="unavailable")
    data = env.get(analysis).json()["data"]
    assert data["status"] == "unavailable" and data["reason_code"] == "provider_rate_limited"
    assert data["summary"] is None and data["risks"] == []


def test_not_generated_is_404_with_reason(env: Env) -> None:
    response = env.get(env.analysis())
    assert response.status_code == 404
    assert response.json()["meta"]["reason"] == "not_generated"


def test_other_organizations_and_unknown_analyses_are_indistinguishable(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis)
    other = env.get(analysis, org=env.org_b)
    unknown = env.get(str(uuid4()))
    assert other.status_code == unknown.status_code == 404
    assert other.json()["error"]["code"] == unknown.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert "Adds retries" not in json.dumps(other.json())


def test_route_is_in_the_openapi_contract(env: Env) -> None:
    spec = env.client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/analyses/{analysis_id}/ai-review"]["get"]
    assert op["operationId"] == "get_ai_review" and "ai-review" in op["tags"]
