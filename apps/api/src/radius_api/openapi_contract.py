"""Public OpenAPI contract: stability levels, shared errors, examples (PRD-15).

The route modules stay untouched. This module post-processes the schema FastAPI
generates so that the committed ``docs/api/openapi.json`` is a deliberate
contract rather than an incidental dump:

* stable ``operationId`` values (the route function name, never the path);
* the API-key headers become ``securitySchemes`` instead of per-route params;
* shared error envelope components (400/401/403/404/409/413/415/422/429);
* ``x-stability`` per tag and operation (see ``docs/api/STABILITY.md``);
* example payloads, ETag/If-Match, pagination and deprecation documentation.

Everything here is deterministic and free of environment-specific values.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI

CONTRACT_MARKER = "x-radius-contract"

#: Stability level of every tag (route group). Unknown tags fail the contract test.
TAG_STABILITY: dict[str, str] = {
    "health": "stable",
    "repositories": "stable",
    "analyses": "stable",
    "confidence": "stable",
    "tests": "stable",
    "graph": "beta",
    "coverage": "beta",
    "intent": "beta",
    "api-keys": "beta",
    "verdict-v2": "alpha",
    "github-webhooks": "internal",
    "authentication": "internal",
}

#: Operation-level overrides (``operationId`` -> level) of the tag default.
OPERATION_STABILITY: dict[str, str] = {
    "get_blast_radius": "beta",
    "get_test_history": "beta",
    "get_test_statistics": "beta",
    "get_recent_executions": "beta",
    "get_flaky_tests": "beta",
}

TAG_DESCRIPTIONS: dict[str, str] = {
    "health": "Liveness and readiness probes. No authentication.",
    "repositories": "Connected repositories and their pull requests.",
    "analyses": "Analyses (verification runs) of a pull request head commit.",
    "confidence": "Evidence-gated confidence report and verification status of an analysis.",
    "tests": "Test selection and CI test-result upload for an analysis.",
    "graph": "Dependency graph of an analysis (shape may still change).",
    "coverage": "Per-test coverage ingestion and queries (shape may still change).",
    "intent": "Intent snapshots, sources and criteria with ETag/If-Match concurrency.",
    "verdict-v2": "Verdict v2 preview. Alpha, behind RADIUS_FEATURE_VERDICT_V2; hidden here.",
    "github-webhooks": "GitHub App webhook receiver. Called by GitHub only; not a client API.",
    "authentication": "Dashboard session endpoints. Internal; not part of the client contract.",
}

_AUTH_DESCRIPTIONS: dict[str, str] = {
    "signup": "Create a dashboard account and start a session.",
    "login": "Exchange credentials for a session cookie.",
    "logout": "End the current session.",
    "me": "Return the signed-in dashboard user.",
    "refresh": "Rotate the session cookie.",
    "forgot_password": "Request a password-reset email. Always accepted (no enumeration).",
    "reset_password": "Set a new password using a reset token.",
    "verify_email": "Confirm an email address using a verification token.",
    "resend_verification": "Send the email-verification message again.",
    "oauth_start": "Begin an OAuth sign-in with the named provider.",
    "oauth_callback": "OAuth provider redirect target; completes sign-in.",
}

_API_KEY_HEADERS = {"x-radius-api-key", "x-radius-organization-id"}
_NOISE_PARAMS = {("content-length", "header")}
_AUTH_ERROR_401_OPS = {"login", "me", "logout", "refresh", "resend_verification"}
_ENVELOPE_REF = {"$ref": "#/components/schemas/Envelope"}
_ANALYSIS_ID = "0b8a3f6e-6c52-4d1e-9a4b-2f4f7a1d9c33"

_ANALYSIS_EXAMPLE: dict[str, Any] = {
    "id": _ANALYSIS_ID,
    "repository_id": "c3f0a9d2-1c0b-4f5e-8b8a-0d6a5e2f9b10",
    "pull_request_id": "a8cbea24-972c-41d7-9e19-50c2382b182f",
    "commit_sha": "a" * 40,
    "status": "completed",
    "started_at": "2026-01-15T10:00:00Z",
    "completed_at": "2026-01-15T10:00:42Z",
    "created_at": "2026-01-15T10:00:00Z",
    "changed_files": [],
    "blast_radius": None,
}
_CONFIDENCE_EXAMPLE: dict[str, Any] = {
    "id": "7d9c1c7a-0e3f-4a0c-b6a5-4f0a1c2d3e4f",
    "analysis_id": _ANALYSIS_ID,
    "confidence_score": 72.5,
    "score_kind": "uncalibrated_heuristic",
    "risk_level": "medium",
    "summary": "Selected tests passed; two changed symbols have no covering test.",
    "evidence": [
        {
            "category": "tests",
            "label": "Selected tests",
            "message": "12 of 14 selected tests executed and passed.",
            "impact": "positive",
            "value": 85.7,
        }
    ],
    "recommendations": ["Add tests for src/auth/reset.py::issue_token."],
    "change_risk": "medium",
    "verification_confidence": 72.5,
    "analysis_completeness": 100.0,
    "verification_status": "insufficient_evidence",
    "generated_at": "2026-01-15T10:01:10Z",
}
_SNAPSHOT_EXAMPLE: dict[str, Any] = {
    "snapshot": {
        "id": "d33464d8-bb3c-485c-8527-35b5e407b075",
        "analysis_id": _ANALYSIS_ID,
        "version": 1,
        "parent_snapshot_id": None,
        "created_at": "2026-01-15T10:00:05Z",
        "criteria_count": 1,
        "state_counts": {"proposed": 1},
        "source_count": 1,
        "etag": '"13475645d350f0f98a75c066"',
        "criteria": [
            {
                "id": "crit_d4e9ed19ee7d4d9c077c7176f41fbfb2",
                "text": "Users must reset password",
                "origin": {
                    "method": "deterministic",
                    "extractor_version": "det-extract-v1",
                    "source_kind": "pr_body",
                    "source_id": "pr-body",
                    "source_hash": "56e9f73f0c4ce8ba3fcfea4caf057402794ada0be540c2d37ef44ae9345bd00f",
                    "retrieved_at": "2026-01-15T10:00:05Z",
                },
                "span": {"source_id": "pr-body", "start": 25, "end": 50},
                "weight": 1.0,
                "testability": "behavioral_testable",
                "testability_rationale": None,
                "state": "proposed",
                "hints": {"paths": [], "tests": [], "label": None},
            }
        ],
        "sources": [],
    },
    "created": True,
    "report": {"diagnostics": [], "carry_events": [], "absent_sources": []},
    "sanitization": {"removed": [], "flagged": []},
}
_INGESTION_EXAMPLE: dict[str, Any] = {
    "id": "e2a4c6d8-0a1b-4c3d-8e5f-6a7b8c9d0e1f",
    "analysis_id": _ANALYSIS_ID,
    "status": "passed",
    "total_tests": 14,
    "passed": 14,
    "failed": 0,
    "skipped": 0,
    "duration_ms": 5120,
    "coverage_percent": None,
    "output": "",
    "upload_count": 1,
    "upload": {
        "id": "f1e2d3c4-b5a6-4978-8a9b-0c1d2e3f4a5b",
        "commit_sha": "a" * 40,
        "body_sha256": "0" * 64,
        "duplicate": False,
        "status": "passed",
        "total_tests": 14,
        "passed": 14,
        "failed": 0,
        "skipped": 0,
        "reported_cases": 14,
    },
    "selected_tests": None,
    "contradictory_cases": [],
    "verification_status": "verified",
}

_STR: dict[str, Any] = {"type": "string"}
_UUID: dict[str, Any] = {"type": "string", "format": "uuid"}
_TS: dict[str, Any] = {"type": "string", "format": "date-time"}
_INT: dict[str, Any] = {"type": "integer"}
_NUM: dict[str, Any] = {"type": "number"}


def _object(
    properties: dict[str, Any],
    required: list[str],
    description: str,
    example: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": required,
    }
    if example is not None:
        schema["examples"] = [example]
    return schema


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _contract_schemas() -> dict[str, Any]:
    not_found = {
        "success": False,
        "data": None,
        "error": {"code": "NOT_FOUND", "message": f"Analysis {_ANALYSIS_ID} was not found."},
        "meta": {},
    }
    evidence_item = _object(
        {
            "category": _STR,
            "label": _STR,
            "message": _STR,
            "impact": _STR,
            "value": _nullable(_NUM),
        },
        ["category", "label", "message", "impact"],
        "One piece of evidence behind the score.",
    )
    return {
        "ErrorBody": _object(
            {
                "code": {"type": "string", "description": "Stable machine-readable code."},
                "message": {"type": "string", "description": "Human text; may change."},
            },
            ["code", "message"],
            "Error detail. Branch on `code`, never on `message`.",
        ),
        "ErrorEnvelope": _object(
            {
                "success": {"const": False},
                "data": {"type": "null"},
                "error": {"$ref": "#/components/schemas/ErrorBody"},
                "meta": {"type": "object", "additionalProperties": True},
            },
            ["success", "error"],
            "Every failure raised by the application uses this envelope.",
            not_found,
        ),
        "Envelope": _object(
            {
                "success": {"type": "boolean"},
                "data": {"description": "Payload; its shape is given per operation."},
                "error": _nullable({"$ref": "#/components/schemas/ErrorBody"}),
                "meta": {"type": "object", "additionalProperties": True},
            },
            ["success"],
            "Success envelope `{success, data, error, meta}` wrapping every JSON payload.",
        ),
        "Analysis": _object(
            {
                "id": _UUID,
                "repository_id": _UUID,
                "pull_request_id": _UUID,
                "commit_sha": _STR,
                "status": {
                    "type": "string",
                    "enum": ["pending", "running", "completed", "failed", "cancelled"],
                },
                "started_at": _TS,
                "completed_at": _nullable(_TS),
                "created_at": _TS,
                "changed_files": {"type": "array", "items": {"type": "object"}},
                "blast_radius": _nullable({"type": "object"}),
            },
            ["id", "repository_id", "pull_request_id", "commit_sha", "status", "created_at"],
            "One verification run of a pull request head commit.",
            _ANALYSIS_EXAMPLE,
        ),
        "ConfidenceReport": _object(
            {
                "id": _nullable(_UUID),
                "analysis_id": _UUID,
                "confidence_score": {**_NUM, "description": "0-100, an uncalibrated heuristic."},
                "score_kind": _STR,
                "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "summary": _STR,
                "evidence": {"type": "array", "items": evidence_item},
                "recommendations": {"type": "array", "items": _STR},
                "change_risk": _STR,
                "verification_confidence": _NUM,
                "analysis_completeness": _NUM,
                "verification_status": {
                    "type": "string",
                    "description": "Evidence-gated verdict, for example verified, failed or "
                    "insufficient_evidence. Treat unknown values as not verified.",
                },
                "generated_at": _TS,
            },
            ["analysis_id", "confidence_score", "risk_level", "summary", "verification_status"],
            "Deterministic confidence report and evidence-gated verification status.",
            _CONFIDENCE_EXAMPLE,
        ),
        "TestIngestion": _object(
            {
                "id": _UUID,
                "analysis_id": _UUID,
                "status": _STR,
                "total_tests": _INT,
                "passed": _INT,
                "failed": _INT,
                "skipped": _INT,
                "duration_ms": _INT,
                "coverage_percent": _nullable(_NUM),
                "output": _STR,
                "upload_count": _INT,
                "upload": {"type": "object"},
                "selected_tests": _nullable({"type": "object"}),
                "contradictory_cases": {"type": "array", "items": _STR},
                "verification_status": _nullable(_STR),
            },
            ["id", "analysis_id", "status", "total_tests", "passed", "failed", "skipped"],
            "Counts aggregated over every upload of the analysis plus this upload.",
            _INGESTION_EXAMPLE,
        ),
    }


_RATE_HEADERS: dict[str, Any] = {
    "Retry-After": {
        "description": "Whole seconds to wait before retrying (at least 1).",
        "schema": {"type": "integer", "minimum": 1},
    },
    "RateLimit-Limit": {"description": "Requests allowed in the window.", "schema": _INT},
    "RateLimit-Remaining": {"description": "Requests left in the window.", "schema": _INT},
    "RateLimit-Reset": {"description": "Seconds until the window resets.", "schema": _INT},
}


def _error_component(
    description: str,
    code: str,
    message: str,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                "examples": {
                    "default": {
                        "value": {
                            "success": False,
                            "data": None,
                            "error": {"code": code, "message": message},
                            "meta": {},
                        }
                    }
                },
            }
        },
    }
    if headers:
        component["headers"] = headers
    return component


def _contract_responses() -> dict[str, Any]:
    validation = _error_component(
        "Validation failed. Request-shape errors use FastAPI's `detail` list; domain "
        "validation errors use the error envelope.",
        "VALIDATION_ERROR",
        "commit_sha query parameter is required.",
    )
    validation["content"]["application/json"]["schema"] = {
        "oneOf": [
            {"$ref": "#/components/schemas/HTTPValidationError"},
            {"$ref": "#/components/schemas/ErrorEnvelope"},
        ]
    }
    return {
        "BadRequest": _error_component(
            "Malformed request.", "BAD_REQUEST", "The request could not be processed."
        ),
        "Unauthorized": _error_component(
            "Session missing or expired (dashboard session endpoints).",
            "UNAUTHORIZED",
            "Not authenticated.",
        ),
        "Forbidden": _error_component(
            "Missing or invalid API key or organization, or a resource of another "
            "organization.",
            "FORBIDDEN",
            "Invalid Radius API key for organization.",
        ),
        "NotFound": _error_component(
            "Resource not found (also returned for resources of other organizations).",
            "NOT_FOUND",
            f"Analysis {_ANALYSIS_ID} was not found.",
        ),
        "Conflict": _error_component(
            "State conflict: stale `If-Match`, illegal state transition, results for a "
            "superseded commit, or an analysis that is not completed.",
            "CONFLICT",
            "Analysis is still pending; wait until it is completed.",
        ),
        "PayloadTooLarge": _error_component(
            "Request body exceeds the size limit.",
            "PAYLOAD_TOO_LARGE",
            "Request body exceeds the allowed size.",
        ),
        "UnsupportedMediaType": _error_component(
            "Body is not JSON where JSON is required.",
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json.",
        ),
        "ValidationFailed": validation,
        "RateLimited": _error_component(
            "Rate limit exceeded. Wait `Retry-After` seconds, then retry.",
            "RATE_LIMITED",
            "Too many requests.",
            headers=_RATE_HEADERS,
        ),
    }


_SECURITY_SCHEMES: dict[str, Any] = {
    "RadiusApiKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Radius-API-Key",
        "description": "API key of the organization named in `X-Radius-Organization-Id`. "
        "Required unless the deployment runs in explicit insecure-dev mode.",
    },
    "RadiusOrganization": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Radius-Organization-Id",
        "description": "UUID of the calling organization. Sent together with the API key.",
    },
    "RadiusSession": {
        "type": "apiKey",
        "in": "cookie",
        "name": "radius_session",
        "description": "Dashboard session cookie. Internal.",
    },
    "GitHubWebhookSignature": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Hub-Signature-256",
        "description": "HMAC-SHA256 of the raw body with the GitHub App webhook secret.",
    },
}

_PARAM_DESCRIPTIONS = {
    "Idempotency-Key": "Client-chosen key; replaying the same key with the same body "
    "returns the first response instead of creating a second resource.",
    "If-Match": "ETag from a previous read; a mismatch returns 409 INTENT_STALE.",
}

#: operationId -> (status, schema component (``[]`` suffix = array), data example)
_EXAMPLES_BY_OPERATION: dict[str, tuple[str, str, Any]] = {
    "start_analysis": ("202", "Analysis", _ANALYSIS_EXAMPLE),
    "rerun_analysis": ("202", "Analysis", _ANALYSIS_EXAMPLE),
    "get_analysis": ("200", "Analysis", _ANALYSIS_EXAMPLE),
    "lookup_analysis": ("200", "Analysis", _ANALYSIS_EXAMPLE),
    "list_analyses": ("200", "Analysis[]", [_ANALYSIS_EXAMPLE]),
    "get_confidence": ("200", "ConfidenceReport", _CONFIDENCE_EXAMPLE),
    "ingest_test_results": ("200", "TestIngestion", _INGESTION_EXAMPLE),
}

_RESPONSE_EXAMPLES: dict[str, tuple[str, Any]] = {
    "submit_source": ("200", _SNAPSHOT_EXAMPLE),
}

_REQUEST_EXAMPLES: dict[str, dict[str, Any]] = {
    "start_analysis": {
        "repositoryId": "c3f0a9d2-1c0b-4f5e-8b8a-0d6a5e2f9b10",
        "pullRequestId": "a8cbea24-972c-41d7-9e19-50c2382b182f",
        "commitSha": "a" * 40,
    },
    "submit_source": {
        "kind": "pr_body",
        "text": "## Acceptance Criteria\n- Users must reset password\n",
    },
    "update_criterion": {"action": "confirm", "reason": "Matches the ticket."},
    "add_criterion": {"text": "Reset links expire after one hour", "reason": "From support."},
}

_API_DESCRIPTION = """\
Software verification API for Radius.

**Envelope.** JSON payloads are wrapped as `{success, data, error, meta}`. Failures use
the shared `ErrorEnvelope`; branch on `error.code`.

**Authentication.** Send `X-Radius-Organization-Id` and `X-Radius-API-Key` on every
non-health route. Both are declared as security schemes, not repeated as parameters.

**Stability.** Every tag and operation carries `x-stability` (`stable`, `beta`, `alpha`
or `internal`). The policy lives in `docs/api/STABILITY.md`. Clients must ignore unknown
response fields.

**Pagination.** List endpoints return the full array, except intent snapshot history
which takes `limit` and `cursor`. Cursors are opaque.

**Concurrency.** Intent reads return an `ETag`; intent writes accept `If-Match` and
answer 409 `INTENT_STALE` on a mismatch. `Idempotency-Key` makes creates replay-safe.

**Rate limits.** 429 carries `Retry-After` and `RateLimit-*` headers.

**Deprecation.** Deprecated operations are flagged `deprecated: true` and answer with
`Deprecation` and `Sunset` headers.
"""


def _route_name(op: dict[str, Any], method: str, path: str) -> str:
    """Recover the route function name from FastAPI's generated operationId.

    FastAPI builds ``{name}{path}_{method}`` with non-word characters replaced by
    ``_``. Stripping that suffix works on every FastAPI version, unlike walking
    ``app.routes`` (whose internals changed between releases).
    """

    suffix = re.sub(r"\W", "_", path) + "_" + method
    generated = op["operationId"]
    return generated[: -len(suffix)] if generated.endswith(suffix) else generated


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/responses/{name}"}


def _error_refs(
    method: str, path: str, op_id: str, tag: str, *, has_body: bool
) -> dict[str, dict[str, str]]:
    if tag == "health":
        return {"429": _ref("RateLimited")}
    refs: dict[str, dict[str, str]] = {"400": _ref("BadRequest")}
    if tag == "authentication":
        if op_id in _AUTH_ERROR_401_OPS:
            refs["401"] = _ref("Unauthorized")
    elif tag != "github-webhooks":
        refs["403"] = _ref("Forbidden")
    lookups = {"lookup_analysis", "get_coverage_for_artifact", "get_tests_for_symbol"}
    if "{" in path or op_id in lookups:
        refs["404"] = _ref("NotFound")
    if method in {"post", "patch", "delete"} and tag not in {"authentication", "github-webhooks"}:
        refs["409"] = _ref("Conflict")
    if has_body:
        refs["413"] = _ref("PayloadTooLarge")
        if tag != "github-webhooks" and op_id != "ingest_test_results":
            refs["415"] = _ref("UnsupportedMediaType")
    refs["422"] = _ref("ValidationFailed")
    refs["429"] = _ref("RateLimited")
    return refs


def _json_content(op: dict[str, Any], status: str) -> dict[str, Any] | None:
    response = op.get("responses", {}).get(status)
    if not response:
        return None
    return response.get("content", {}).get("application/json")


def _clean_parameters(op: dict[str, Any]) -> tuple[bool, bool]:
    """Drop auth/noise params from ``op``; return (api key used, session used)."""

    params = []
    protected = False
    has_session = False
    for param in op.get("parameters", []):
        name = param["name"].lower()
        if (name, param["in"]) in _NOISE_PARAMS:
            continue
        if param["in"] == "header" and name in _API_KEY_HEADERS:
            protected = True
            continue
        if param["in"] == "cookie" and param["name"] == "radius_session":
            has_session = True
            continue
        if param["name"] in _PARAM_DESCRIPTIONS and not param.get("description"):
            param["description"] = _PARAM_DESCRIPTIONS[param["name"]]
        params.append(param)
    if params:
        op["parameters"] = params
    else:
        op.pop("parameters", None)
    return protected, has_session


def _merge_errors(op: dict[str, Any], refs: dict[str, dict[str, str]]) -> dict[str, Any]:
    responses = op["responses"]
    responses.pop("422", None)  # FastAPI's generic one; replaced by the shared component
    for status, ref in refs.items():
        existing = responses.get(status)
        if existing and existing.get("description") and "$ref" not in existing:
            # Keep an operation-specific description (intent routes) and attach
            # the shared envelope as its content.
            merged = dict(existing)
            merged["content"] = {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
            }
            responses[status] = merged
        else:
            responses[status] = ref
    return responses


def _attach_examples(op: dict[str, Any], op_id: str) -> None:
    spec = _EXAMPLES_BY_OPERATION.get(op_id)
    if spec:
        status, component, example = spec
        content = _json_content(op, status)
        if content is not None:
            if component.endswith("[]"):
                data_schema: dict[str, Any] = {
                    "type": "array",
                    "items": {"$ref": f"#/components/schemas/{component[:-2]}"},
                }
            else:
                data_schema = {"$ref": f"#/components/schemas/{component}"}
            content["schema"] = {
                "allOf": [
                    _ENVELOPE_REF,
                    {"type": "object", "properties": {"data": data_schema}},
                ]
            }
            content["examples"] = {
                "default": {
                    "value": {"success": True, "data": example, "error": None, "meta": {}}
                }
            }
    extra = _RESPONSE_EXAMPLES.get(op_id)
    if extra:
        content = _json_content(op, extra[0])
        if content is not None:
            content["examples"] = {
                "default": {
                    "value": {"success": True, "data": extra[1], "error": None, "meta": {}}
                }
            }
    request_example = _REQUEST_EXAMPLES.get(op_id)
    if request_example is not None:
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body is not None:
            body["examples"] = {"default": {"value": request_example}}


def _decorate_operation(
    op: dict[str, Any], method: str, path: str, op_ids: set[str]
) -> None:
    tag = (op.get("tags") or ["untagged"])[0]
    name = _route_name(op, method, path)
    op_id = name if name not in op_ids else f"{tag.replace('-', '_')}_{name}"
    op_ids.add(op_id)
    op["operationId"] = op_id
    op["x-stability"] = OPERATION_STABILITY.get(op_id, TAG_STABILITY.get(tag, "internal"))
    if not op.get("description"):
        op["description"] = _AUTH_DESCRIPTIONS.get(op_id, op.get("summary", op_id))

    protected, has_session = _clean_parameters(op)
    if protected:
        op["security"] = [{"RadiusApiKey": [], "RadiusOrganization": []}]
    elif has_session:
        op["security"] = [{"RadiusSession": []}]
    elif tag == "github-webhooks":
        op["security"] = [{"GitHubWebhookSignature": []}]
    else:
        op["security"] = []

    refs = _error_refs(method, path, op_id, tag, has_body="requestBody" in op)
    responses = _merge_errors(op, refs)

    for status in responses:
        content = _json_content(op, status) if status.startswith("2") else None
        if content is not None and content.get("schema") == {}:
            content["schema"] = dict(_ENVELOPE_REF)
    _attach_examples(op, op_id)

    if op_id == "ingest_test_results":
        op["requestBody"] = {
            "required": True,
            "description": "One CI test report: JUnit XML or Radius JSON, at most 20 MiB. "
            "Bound to `commit_sha`; replaying an identical body is idempotent.",
            "content": {
                "application/xml": {"schema": {"type": "string"}},
                "text/xml": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
            },
        }

    if tag == "intent":
        names = {p["name"] for p in op.get("parameters", [])}
        if "If-Match" in names or op_id in {"get_intent", "get_snapshot"}:
            for status in ("200", "201"):
                if status in responses:
                    responses[status].setdefault("headers", {})["ETag"] = {
                        "description": "Opaque version of the snapshot; send it back as "
                        "`If-Match` on the next write.",
                        "schema": {"type": "string"},
                    }
    if op.get("deprecated"):
        for status, response in responses.items():
            if status.startswith("2"):
                headers = response.setdefault("headers", {})
                headers["Deprecation"] = {
                    "description": "Present because the operation is deprecated.",
                    "schema": {"type": "string"},
                }
                headers["Sunset"] = {
                    "description": "HTTP-date after which the operation may be removed.",
                    "schema": {"type": "string"},
                }
    op["responses"] = {key: responses[key] for key in sorted(responses)}


def decorate_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Apply the contract quality pass to ``schema`` (in place) and return it."""

    op_ids: set[str] = set()
    used_tags: set[str] = set()
    for path, item in schema.get("paths", {}).items():
        for method, op in item.items():
            _decorate_operation(op, method, path, op_ids)
            used_tags.update(op.get("tags", []))

    info = schema["info"]
    info["description"] = _API_DESCRIPTION
    info["license"] = {"name": "Apache-2.0", "identifier": "Apache-2.0"}
    info["x-stability-policy"] = "docs/api/STABILITY.md"

    schema["tags"] = [
        {
            "name": tag,
            "description": TAG_DESCRIPTIONS.get(tag, ""),
            "x-stability": TAG_STABILITY.get(tag, "internal"),
        }
        for tag in sorted(used_tags)
    ]
    components = schema.setdefault("components", {})
    components.setdefault("schemas", {}).update(_contract_schemas())
    components["responses"] = _contract_responses()
    components["securitySchemes"] = dict(_SECURITY_SCHEMES)
    schema[CONTRACT_MARKER] = 1
    return schema


def install_openapi_contract(app: FastAPI) -> None:
    """Make ``app.openapi()`` return the decorated contract document."""

    original = app.openapi

    def openapi() -> dict[str, Any]:
        cached = app.openapi_schema
        if cached is not None and CONTRACT_MARKER in cached:
            return cached
        app.openapi_schema = None
        schema = original()
        decorate_schema(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
