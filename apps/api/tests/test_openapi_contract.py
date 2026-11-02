"""OpenAPI contract tests (PRD-15): committed export, quality pass, diff guard."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_api.openapi_contract import OPERATION_STABILITY, TAG_STABILITY

ROOT = Path(__file__).resolve().parents[3]
SPEC_FILE = ROOT / "docs" / "api" / "openapi.json"
METHODS = {"get", "put", "post", "delete", "patch"}
ERROR_COMPONENTS = {
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "Conflict",
    "PayloadTooLarge",
    "UnsupportedMediaType",
    "ValidationFailed",
    "RateLimited",
}


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_radius_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def exporter():
    return _load_script("export_openapi")


@pytest.fixture(scope="module")
def differ():
    return _load_script("openapi_diff")


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(SPEC_FILE.read_bytes().decode("utf-8"))


def _operations(spec: dict):
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                yield method, path, op


def test_committed_spec_is_up_to_date(exporter) -> None:
    generated = exporter.render(exporter.generate_spec())
    raw = SPEC_FILE.read_bytes()
    assert b"\r" not in raw, "docs/api/openapi.json must use LF endings"
    assert raw.decode("utf-8") == generated, (
        "docs/api/openapi.json is stale: run `python scripts/export_openapi.py`"
    )


def test_check_mode_reports_staleness(exporter, tmp_path) -> None:
    stale = tmp_path / "openapi.json"
    stale.write_text("{}\n", encoding="utf-8")
    assert exporter.main(["--check", "--output", str(stale)]) == 1
    assert exporter.main(["--output", str(stale)]) == 0
    assert exporter.main(["--check", "--output", str(stale)]) == 0


def test_export_is_deterministic_and_environment_free(exporter, committed, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", "on")
    monkeypatch.setenv("API_KEYS", f"{uuid4()}:secret-value")
    assert exporter.render(exporter.generate_spec()) == exporter.render(committed)
    text = SPEC_FILE.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:\\\\|/home/|/Users/|localhost:\d+|secret-value", text)


def test_document_is_openapi_31_with_unique_operation_ids(committed) -> None:
    assert committed["openapi"].startswith("3.1")
    ids = [op["operationId"] for _, _, op in _operations(committed)]
    assert len(ids) == len(set(ids))
    for op_id in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", op_id), op_id
        assert "_api_v1_" not in op_id, f"{op_id} still path-derived"


def test_every_public_route_is_documented(committed) -> None:
    declared_tags = {tag["name"] for tag in committed["tags"]}
    for method, path, op in _operations(committed):
        where = f"{method.upper()} {path}"
        assert op.get("summary"), where
        assert op.get("description"), where
        assert op.get("tags"), where
        assert set(op["tags"]) <= declared_tags, where
        assert op["x-stability"] in {"stable", "beta", "alpha", "internal"}, where
        assert "security" in op, where
        assert {"429"} <= set(op["responses"]), where
        names = {p["name"].lower() for p in op.get("parameters", [])}
        assert not names & {"x-radius-api-key", "x-radius-organization-id"}, where
    assert {t["name"] for t in committed["tags"]} <= set(TAG_STABILITY)
    assert set(OPERATION_STABILITY) <= {op["operationId"] for *_, op in _operations(committed)}


def test_security_schemes_and_shared_error_components(committed) -> None:
    schemes = committed["components"]["securitySchemes"]
    assert schemes["RadiusApiKey"]["name"] == "X-Radius-API-Key"
    assert schemes["RadiusOrganization"]["name"] == "X-Radius-Organization-Id"
    assert set(committed["components"]["responses"]) == ERROR_COMPONENTS
    assert "ErrorEnvelope" in committed["components"]["schemas"]
    protected = [op for _, _, op in _operations(committed) if op["security"]]
    assert any(
        op["security"] == [{"RadiusApiKey": [], "RadiusOrganization": []}] for op in protected
    )
    rate_limited = committed["components"]["responses"]["RateLimited"]
    assert "Retry-After" in rate_limited["headers"]
    refs = {
        status: response.get("$ref")
        for status, response in committed["paths"]["/api/v1/analyses"]["post"]["responses"].items()
    }
    assert refs["403"] == "#/components/responses/Forbidden"
    assert refs["413"] == "#/components/responses/PayloadTooLarge"
    assert refs["415"] == "#/components/responses/UnsupportedMediaType"
    assert refs["429"] == "#/components/responses/RateLimited"


def test_main_resources_have_examples(committed) -> None:
    by_id = {op["operationId"]: op for _, _, op in _operations(committed)}
    for op_id in ("get_analysis", "list_analyses", "get_confidence", "ingest_test_results"):
        content = by_id[op_id]["responses"]["200"]["content"]["application/json"]
        assert content["examples"]["default"]["value"]["success"] is True, op_id
    assert "examples" in by_id["submit_source"]["responses"]["200"]["content"]["application/json"]
    assert "examples" in by_id["start_analysis"]["requestBody"]["content"]["application/json"]
    schemas = committed["components"]["schemas"]
    for name in ("Analysis", "ConfidenceReport", "TestIngestion", "ErrorEnvelope"):
        assert schemas[name]["examples"], name


def test_etag_if_match_and_pagination_are_documented(committed) -> None:
    by_id = {op["operationId"]: op for _, _, op in _operations(committed)}
    for op_id in ("get_intent", "get_snapshot", "update_criterion", "submit_source"):
        ok = by_id[op_id]["responses"].get("200") or by_id[op_id]["responses"]["201"]
        assert "ETag" in ok["headers"], op_id
    for op_id in ("update_criterion", "add_criterion", "submit_source", "rebuild"):
        params = {p["name"]: p for p in by_id[op_id]["parameters"]}
        assert params["If-Match"]["description"], op_id
    names = {p["name"] for p in by_id["list_snapshots"]["parameters"]}
    assert {"limit", "cursor"} <= names
    assert "Pagination" in committed["info"]["description"]


def test_stability_levels_follow_the_policy(committed) -> None:
    by_id = {op["operationId"]: op for _, _, op in _operations(committed)}
    assert by_id["get_confidence"]["x-stability"] == "stable"
    assert by_id["get_intent"]["x-stability"] == "beta"
    assert by_id["handle_github_webhook"]["x-stability"] == "internal"
    assert by_id["login"]["x-stability"] == "internal"


def test_verdict_v2_is_hidden_by_default_and_when_enabled(committed, monkeypatch) -> None:
    assert not [p for p in committed["paths"] if p.endswith("/verdict")]
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    monkeypatch.setenv("RADIUS_FEATURE_VERDICT_V2", "on")
    get_api_settings.cache_clear()
    app = create_app()
    assert not [p for p in app.openapi()["paths"] if p.endswith("/verdict")]
    client = TestClient(app)
    response = client.get(
        f"/api/v1/analyses/{uuid4()}/verdict", headers={"X-Radius-Organization-Id": str(uuid4())}
    )
    assert response.status_code == 404  # the route exists, it is just undocumented


def test_deprecated_operations_declare_deprecation_headers(exporter) -> None:
    from fastapi import FastAPI
    from radius_api.openapi_contract import install_openapi_contract

    app = FastAPI()

    @app.get("/old", deprecated=True, tags=["analyses"])
    def old() -> dict:
        """Old route."""
        return {}

    install_openapi_contract(app)
    op = app.openapi()["paths"]["/old"]["get"]
    assert op["deprecated"] is True
    assert {"Deprecation", "Sunset"} <= set(op["responses"]["200"]["headers"])


def test_real_responses_match_the_documented_shapes(committed, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_ALLOW_INSECURE_DEV", "true")
    monkeypatch.setenv("RADIUS_ENV", "test")
    get_api_settings.cache_clear()
    client = TestClient(create_app())
    org = str(uuid4())
    headers = {"X-Radius-Organization-Id": org}
    repo = client.post(
        "/api/v1/repositories",
        headers=headers,
        json={
            "organizationId": org,
            "repositoryId": 7,
            "name": "radius",
            "owner": "acme",
            "defaultBranch": "main",
            "cloneUrl": "https://github.com/acme/radius.git",
            "visibility": "private",
        },
    ).json()["data"]["id"]
    analysis = client.post(
        "/api/v1/analyses",
        headers=headers,
        json={"repositoryId": repo, "pullRequestId": str(uuid4()), "commitSha": "a" * 40},
    ).json()["data"]
    schema = committed["components"]["schemas"]["Analysis"]
    assert set(schema["required"]) <= set(analysis)
    assert set(schema["properties"]) >= set(analysis)
    assert analysis["status"] in schema["properties"]["status"]["enum"]
    missing = client.get(f"/api/v1/analyses/{uuid4()}", headers=headers)
    body = missing.json()
    assert missing.status_code == 404
    assert set(body) >= {"success", "error"} and set(body["error"]) == {"code", "message"}


# --- diff guard -----------------------------------------------------------------


def test_diff_of_identical_specs_is_empty(differ, committed) -> None:
    assert differ.diff_specs(committed, copy.deepcopy(committed)) == []


def test_diff_flags_removal_rename_and_required_changes(differ, committed) -> None:
    new = copy.deepcopy(committed)
    path = "/api/v1/analyses/{analysis_id}"
    del new["paths"][path]["get"]
    new["paths"]["/api/v1/analyses"]["get"]["operationId"] = "list_all_analyses"
    new["paths"]["/api/v1/analyses/lookup"]["get"]["parameters"].append(
        {"name": "extra", "in": "query", "required": True, "schema": {"type": "string"}}
    )
    new["components"]["schemas"]["StartAnalysisRequest"]["required"].append("extra")
    del new["components"]["schemas"]["Analysis"]["properties"]["commit_sha"]
    findings = differ.diff_specs(committed, new)
    messages = [f.render() for f in findings]
    assert any("GET /api/v1/analyses/{analysis_id}: operation removed" in m for m in messages)
    assert any("operationId 'list_analyses' -> 'list_all_analyses'" in m for m in messages)
    assert any("new required parameter query:extra" in m for m in messages)
    assert any("new required request property" in m for m in messages)
    assert any("response 200 .data.commit_sha" in m or "commit_sha" in m for m in messages)
    assert all(f.level == "breaking" for f in findings)
    assert differ.unacknowledged_breaking(findings, {f.key for f in findings}) == []


def test_diff_treats_beta_as_warning_and_ignores_additions(differ, committed) -> None:
    new = copy.deepcopy(committed)
    intent = "/api/v1/analyses/{analysis_id}/intent"
    del new["paths"][intent]["get"]
    new["paths"]["/api/v1/brand-new"] = {
        "get": {"operationId": "brand_new", "x-stability": "stable", "responses": {"200": {}}}
    }
    findings = differ.diff_specs(committed, new)
    assert [f.level for f in findings] == ["warning"]
    assert differ.unacknowledged_breaking(findings, set()) == []


def test_diff_type_changes_are_directional(differ) -> None:
    def spec(request_type: str, response_type: str) -> dict:
        schema = {"properties": {"n": {"type": request_type}}, "type": "object"}
        return {
            "paths": {
                "/x": {
                    "post": {
                        "operationId": "x",
                        "x-stability": "stable",
                        "requestBody": {
                            "required": True,
                            "content": {"application/json": {"schema": schema}},
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"n": {"type": response_type}},
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            }
        }

    assert differ.diff_specs(spec("integer", "integer"), spec("integer", "integer")) == []
    broken = differ.diff_specs(spec("integer", "integer"), spec("string", "string"))
    assert len(broken) == 2


def test_no_breaking_change_against_previous_committed_version(differ) -> None:
    """Compare against the spec on the base branch (CI) when git can provide it."""

    for ref in ("origin/develop", "develop"):
        previous = differ.git_show(ref)
        if previous is not None:
            break
    else:
        pytest.skip("no previous docs/api/openapi.json reachable in git")
    current = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    findings = differ.diff_specs(previous, current)
    blocking = differ.unacknowledged_breaking(findings, differ.load_acknowledged())
    assert not blocking, "\n".join(f.render() for f in blocking)


def test_scripts_run_as_commands() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "openapi_diff.py"), "--old", str(SPEC_FILE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No unacknowledged breaking changes." in result.stdout
