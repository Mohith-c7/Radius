"""Verdict v2 API (VS-09) and the CI-upload republish enqueue (VS-07); memory and SQL."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from radius_shared.verdict_v2_repository import SqlVerdictV2Repository
from radius_shared.verdict_v2_testing import make_bundle, make_error_bundle
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

SCHEMA_PATH = next(
    p / "docs/research/design/verdict_v2.schema.json"
    for p in Path(__file__).resolve().parents
    if (p / "docs/research/design/verdict_v2.schema.json").is_file()
)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(value: Any, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Stdlib validator for the JSON-Schema subset of verdict_v2.schema.json."""

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [*errors, f"{path}: expected type {names}, got {type(value).__name__}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: does not match pattern")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{path}.{key}")
            elif isinstance(extra, dict):
                errors += validate(item, extra, f"{path}.{key}")
            elif extra is False:
                errors.append(f"{path}: unexpected property {key!r}")
    return errors
HEAD = "a" * 40
JUNIT = (
    '<?xml version="1.0"?><testsuite name="p" tests="1" errors="0" failures="0" '
    'skipped="0" time="0.1"><testcase classname="tests.t" name="test_a" time="0.1"/>'
    "</testsuite>"
)


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
            json={
                "repositoryId": repo.json()["data"]["id"],
                "pullRequestId": str(uuid4()),
                "commitSha": HEAD,
            },
        )
        assert started.status_code == 202, started.text
        return started.json()["data"]["id"]

    def complete(self, analysis: str) -> None:
        if self.engine is None:
            self.container.analysis_service().complete_analysis(UUID(analysis))
            return
        with Session(self.engine) as session:
            row = session.get(db_models.Analysis, UUID(analysis))
            row.status = db_enums.AnalysisStatus.COMPLETED
            session.commit()

    def store(self, org: str, analysis: str, bundle: dict, mode: str = "on") -> None:
        if self.engine is None:
            self.container.verdict_v2_repository.save(
                UUID(org), UUID(analysis), bundle, mode=mode
            )
            return
        with Session(self.engine) as session:
            SqlVerdictV2Repository(session).save(
                UUID(org), UUID(analysis), bundle, mode=mode
            )
            session.commit()

    def pending(self, org: str, analysis: str):
        if self.engine is None:
            return self.container.verdict_v2_repository.get_request(UUID(org), UUID(analysis))
        with Session(self.engine) as session:
            return SqlVerdictV2Repository(session).get_request(UUID(org), UUID(analysis))

    def get(self, analysis: str, org: str | None = None, path: str = "verdict-v2", **headers):
        return self.client.get(
            f"/api/v1/analyses/{analysis}/{path}",
            headers={**self.headers(org), **headers},
        )


def _build(monkeypatch, tmp_path, backend: str, flag: str | None) -> Env:
    orgs = [str(uuid4()), str(uuid4())]
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    monkeypatch.delenv("RADIUS_FEATURE_VERDICT_V2", raising=False)
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
    return Env(TestClient(create_app()), orgs, engine)


@pytest.fixture(params=["memory", "sql"])
def backend(request) -> str:
    return request.param


@pytest.fixture
def env(monkeypatch, tmp_path, backend) -> Env:
    return _build(monkeypatch, tmp_path, backend, "on")


# -- flag ------------------------------------------------------------------


def test_flag_off_is_404_disabled_and_absent_from_openapi(monkeypatch, tmp_path, backend) -> None:
    env = _build(monkeypatch, tmp_path, backend, None)
    analysis = env.analysis()

    response = env.get(analysis)

    assert response.status_code == 404
    assert response.json()["meta"]["reason"] == "disabled"
    assert env.get(analysis, path="verdict").json()["meta"]["reason"] == "disabled"
    paths = env.client.get("/openapi.json").json()["paths"]
    assert not any("verdict" in p for p in paths)


def test_flag_on_documents_only_the_canonical_route(env: Env) -> None:
    paths = env.client.get("/openapi.json").json()["paths"]
    assert "/api/v1/analyses/{analysis_id}/verdict-v2" in paths
    assert "/api/v1/analyses/{analysis_id}/verdict" not in paths
    assert any(p.endswith("/confidence") for p in paths)


def test_shadow_mode_serves_the_stored_verdict(monkeypatch, tmp_path, backend) -> None:
    env = _build(monkeypatch, tmp_path, backend, "shadow")
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis), mode="shadow")
    body = env.get(analysis).json()["data"]
    assert body["mode"] == "shadow"


# -- reads -----------------------------------------------------------------


def test_not_computed_is_404_with_reason(env: Env) -> None:
    analysis = env.analysis()
    response = env.get(analysis)
    assert response.status_code == 404
    assert response.json()["meta"]["reason"] == "not_computed"


def test_computed_verdict_conforms_to_the_schema_and_is_honest_about_score(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis))

    response = env.get(analysis)

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    data = response.json()["data"]
    assert validate(data, SCHEMA) == []
    assert data["verdict_version"] == 2
    assert data["score"] is None
    assert data["score_kind"] == "none"
    assert data["trust_probability"] is None
    assert data["verdict"] == "insufficient_evidence"
    assert data["analysis_id"] == analysis
    assert data["summary"]["criteria_total"] == 2
    assert (data["summary"]["weak"], data["summary"]["unevidenced"]) == (1, 1)
    first = data["criteria"][0]
    assert first["items"][0]["test_id"].endswith("test_rejects_missing_digit")
    assert first["items"][0]["outcome"] == "passed"
    assert data["next_actions"][0]["code"] in {"single_test", "no_linked_test"}
    assert data["justification"]["decided_by"] == "R2b"
    assert data["reasons"][0]["rule_id"] == "R2b"
    assert "v1" in data


def test_payload_is_honest_about_alpha_provenance_and_wording(env: Env) -> None:
    from radius_github.verdict_v2 import markdown as md
    from radius_shared import verdict_v2_wording as wording

    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis))

    data = env.get(analysis).json()["data"]

    assert validate(data, SCHEMA) == []
    assert (data["alpha"], data["calibrated"], data["evidence_basis"]) == (True, False, "static_only")
    assert data["contract_version"] == "verdict-v2-contract-5"
    first, second = data["criteria"]
    assert first["provenance"] == "author_head_spec"
    assert first["hints"][0]["provenance"] == "author_head_spec"
    assert second["provenance"] == "author_pr_body" and second["hints"] == []
    assert data["summary"]["author_hint_criteria"] == 0
    # presentation layer: internal enum values stay, user-visible text says "supported"
    pres = data["presentation"]
    assert pres["state_labels"]["proven"] == "SUPPORTED"
    assert pres["verdict_label"] == "Not verified - insufficient evidence"
    assert "0 of 2 stated criteria supported by static evidence" in pres["summary_text"]
    assert "proven" not in pres["summary_text"].lower()
    # the three presentations (API text, Markdown renderer) share one vocabulary
    assert wording.LEGEND == md.LEGEND
    assert dict(wording.STATE_LABELS) == md.STATE_LABELS
    assert dict(wording.VERDICT_LABELS) == md.VERDICT_LABELS
    assert wording.DISCLAIMER.split(";")[0].lower().startswith("alpha: static evidence only")


def test_verified_verdict_is_never_worded_as_verified_by_the_api(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis, verdict="verified"))

    data = env.get(analysis).json()["data"]

    assert data["verdict"] == "verified"  # contract value unchanged
    assert data["presentation"]["verdict_label"] == "Supported by static evidence (alpha)"
    assert data["alpha"] is True and data["calibrated"] is False


def test_alias_route_serves_the_same_payload(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis))
    assert env.get(analysis, path="verdict").json() == env.get(analysis).json()


def test_error_row_is_served_honestly_with_null_verdict(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_error_bundle(analysis))

    data = env.get(analysis).json()["data"]

    assert data["status"] == "error"
    assert data["verdict"] is None
    assert data["criteria"] == []
    assert data["error"] == {"code": "TimeoutError", "fallback": "v1"}
    assert "stage A exceeded" not in json.dumps(data)  # error_detail is never served


def test_newest_revision_wins(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis, variant="a"))
    env.store(env.org_a, analysis, make_bundle(analysis, variant="b", verdict="verified"))
    data = env.get(analysis).json()["data"]
    assert (data["revision"], data["verdict"]) == (2, "verified")


def test_untrusted_text_is_json_not_html(env: Env) -> None:
    analysis = env.analysis()
    evil = "<script>alert(1)</script> @everyone"
    env.store(env.org_a, analysis, make_bundle(analysis, criterion_text=evil))
    response = env.get(analysis)
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["data"]["criteria"][0]["text"] == evil


# -- etag ------------------------------------------------------------------


def test_etag_and_conditional_get(env: Env) -> None:
    analysis = env.analysis()
    env.store(env.org_a, analysis, make_bundle(analysis))
    first = env.get(analysis)
    etag = first.headers["ETag"]
    assert etag.startswith('"') and etag.endswith('"')
    assert env.get(analysis).headers["ETag"] == etag

    cached = env.get(analysis, **{"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.content == b""

    env.store(env.org_a, analysis, make_bundle(analysis, variant="b"))
    fresh = env.get(analysis, **{"If-None-Match": etag})
    assert fresh.status_code == 200
    assert fresh.headers["ETag"] != etag


# -- tenant isolation -------------------------------------------------------


def test_other_organization_gets_404_and_no_data(env: Env) -> None:
    analysis_b = env.analysis(env.org_b)
    env.store(env.org_b, analysis_b, make_bundle(analysis_b))

    other = env.get(analysis_b, org=env.org_a)
    unknown = env.get(str(uuid4()), org=env.org_a)

    assert other.status_code == unknown.status_code == 404
    assert other.json()["error"]["code"] == unknown.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert "criteria" not in other.text and analysis_b not in other.text.replace(
        "ANALYSIS_NOT_FOUND", ""
    )
    assert env.get(analysis_b, org=env.org_b).status_code == 200


def test_a_verdict_stored_under_another_org_is_never_served(env: Env) -> None:
    analysis_a = env.analysis(env.org_a)
    env.store(env.org_b, analysis_a, make_bundle(analysis_a))  # wrong tenant on purpose
    response = env.get(analysis_a, org=env.org_a)
    assert response.status_code == 404
    assert response.json()["meta"]["reason"] == "not_computed"


# -- v1 unchanged -----------------------------------------------------------


def test_v1_confidence_response_is_unchanged_by_v2(env: Env) -> None:
    analysis = env.analysis()
    env.complete(analysis)
    upload = env.client.post(
        f"/api/v1/analyses/{analysis}/tests/results",
        params={"commit_sha": HEAD},
        headers={**env.headers(), "Content-Type": "application/xml"},
        content=JUNIT,
    )
    assert upload.status_code == 200
    before = env.client.get(f"/api/v1/analyses/{analysis}/confidence", headers=env.headers())
    env.store(env.org_a, analysis, make_bundle(analysis))
    after = env.client.get(f"/api/v1/analyses/{analysis}/confidence", headers=env.headers())

    assert before.status_code == after.status_code == 200
    assert before.json() == after.json()
    v2 = env.get(analysis).json()["data"]
    assert v2["v1"]["score_kind"] == before.json()["data"]["score_kind"]
    assert v2["v1"]["confidence_score"] == before.json()["data"]["confidence_score"]
    assert v2["v1"]["verification_status"] == before.json()["data"]["verification_status"]


def test_v1_confidence_is_byte_identical_with_the_flag_off_and_on(
    monkeypatch, tmp_path, backend
) -> None:
    bodies = []
    for flag in (None, "on"):
        folder = tmp_path / f"flag-{flag}"
        folder.mkdir()
        env = _build(monkeypatch, folder, backend, flag)
        analysis = env.analysis()
        env.complete(analysis)
        env.client.post(
            f"/api/v1/analyses/{analysis}/tests/results",
            params={"commit_sha": HEAD},
            headers={**env.headers(), "Content-Type": "application/xml"},
            content=JUNIT,
        )
        data = env.client.get(
            f"/api/v1/analyses/{analysis}/confidence", headers=env.headers()
        ).json()["data"]
        for key in ("id", "analysis_id", "generated_at"):
            data.pop(key, None)
        bodies.append(data)
    assert bodies[0] == bodies[1]


# -- republish enqueue (VS-07) ---------------------------------------------


def test_ci_upload_enqueues_exactly_one_request_and_replays_collapse(env: Env) -> None:
    analysis = env.analysis()
    env.complete(analysis)
    assert env.pending(env.org_a, analysis) is None

    for _ in range(2):
        response = env.client.post(
            f"/api/v1/analyses/{analysis}/tests/results",
            params={"commit_sha": HEAD},
            headers={**env.headers(), "Content-Type": "application/xml"},
            content=JUNIT,
        )
        assert response.status_code == 200

    pending = env.pending(env.org_a, analysis)
    assert pending is not None and pending.reason == "ci_results"
    assert env.pending(env.org_b, analysis) is None


def test_ci_upload_enqueues_nothing_with_the_flag_off(monkeypatch, tmp_path, backend) -> None:
    env = _build(monkeypatch, tmp_path, backend, None)
    analysis = env.analysis()
    env.complete(analysis)
    response = env.client.post(
        f"/api/v1/analyses/{analysis}/tests/results",
        params={"commit_sha": HEAD},
        headers={**env.headers(), "Content-Type": "application/xml"},
        content=JUNIT,
    )
    assert response.status_code == 200
    assert env.pending(env.org_a, analysis) is None


def test_rejected_upload_does_not_enqueue(env: Env) -> None:
    analysis = env.analysis()
    env.complete(analysis)
    response = env.client.post(
        f"/api/v1/analyses/{analysis}/tests/results",
        params={"commit_sha": "b" * 40},  # not the analysed head
        headers={**env.headers(), "Content-Type": "application/xml"},
        content=JUNIT,
    )
    assert response.status_code == 409
    assert env.pending(env.org_a, analysis) is None


# -- schema example --------------------------------------------------------


def test_the_design_example_payload_validates_against_the_same_schema() -> None:
    example = json.loads(
        (SCHEMA_PATH.parent / "verdict_v2.example.08.json").read_text(encoding="utf-8")
    )
    example.pop("_example_note", None)
    assert validate(example, SCHEMA) == []
