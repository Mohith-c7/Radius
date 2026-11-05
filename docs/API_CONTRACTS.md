# 10_API_Contracts.md

# API Contracts

**Project:** Radius

**Version:** 1.0

---

# Overview

This document defines the public API surface of Radius.

The API follows REST principles and acts as the boundary between clients and the application layer.

The API is responsible for:

- Request validation
- Authentication
- Authorization
- Coordinating domain services
- Returning standardized responses

Business logic must never exist inside controllers.

---

# API Standards

## Base URL

/api/v1

---

## Response Format

Every response follows a consistent envelope.

Success

{
  "success": true,
  "data": {},
  "meta": {}
}

Failure

{
  "success": false,
  "error": {
    "code": "REPOSITORY_NOT_FOUND",
    "message": "Repository does not exist."
  }
}

---

# Authentication

Phase 1

GitHub OAuth

JWT Access Token

Refresh Token

---

# Authorization

Organization Admin

Developer

Worker

GitHub Webhook

Each endpoint specifies the required role.

---

# Repository APIs

---

## HTTP limits and rate limiting

Every response carries security headers (`X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Referrer-Policy`, `Cache-Control: no-store`, ...). See `docs/security/HTTP_HARDENING.md`.

Failures produced before routing use the standard envelope:

| Status | `error.code` | When | Notes |
|---|---|---|---|
| 413 | `PAYLOAD_TOO_LARGE` | body over the cap (1 MiB default, 5 MiB webhook, 20 MiB test-report upload) | `meta.max_bytes` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | POST/PUT/PATCH with a body that is not `application/json` (or `+json`) | not applied to webhook and test-report upload |
| 429 | `RATE_LIMITED` | token bucket empty | `Retry-After`, `meta.retry_after_seconds`, `meta.bucket` |

    HTTP/1.1 429 Too Many Requests
    Retry-After: 29
    RateLimit-Limit: 10
    RateLimit-Remaining: 0
    RateLimit-Reset: 60
    RateLimit-Policy: 10;w=60

    {"success": false, "data": null,
     "error": {"code": "RATE_LIMITED", "message": "Too many requests. Retry after the interval in Retry-After."},
     "meta": {"retry_after_seconds": 29, "bucket": "auth"}}

Rate limited routes also return `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` (seconds until the bucket is full) and `RateLimit-Policy` (`<requests>;w=<window>`) on success. Names follow draft-ietf-httpapi-ratelimit-headers (the `-07` field names); the draft may change. `/health` and `/ready` are never limited. Existing intent size errors keep `422 PAYLOAD_TOO_LARGE` for bodies over 256 KiB.

---

## POST /repositories

### Purpose

Connect a repository to Radius.

### Actor

Organization Admin

### Request

{
  "provider": "github",
  "repositoryId": "...",
  "organizationId": "..."
}

### Success

201 Created

Returns Repository.

### Domain Service

RepositoryApplicationService

### Events

RepositoryConnected

RepositorySynchronizationStarted

---

## GET /repositories

Returns repositories visible to the user.

---

## GET /repositories/{repositoryId}

Returns repository details.

---

## DELETE /repositories/{repositoryId}

Disconnect repository.

Historical analyses remain.

---

# Pull Request APIs

---

## GET /repositories/{repositoryId}/pull-requests

Returns Pull Requests.

---

## GET /pull-requests/{id}

Returns Pull Request details.

---

# Analysis APIs

---

## POST /analyses

Purpose

Trigger manual analysis.

Actor

Developer

Request

{
    "repositoryId": "...",
    "pullRequestId": "..."
}

Response

Analysis object.

Events

AnalysisStarted

---

## GET /analyses

List analyses, newest first.

Query: `repositoryId`, `pullRequestId`, `status` (filters), `limit` (1 to 500, default 100) and `offset` (0 or more). Values outside the range answer 422. `GET /repositories` and `GET /repositories/{id}/pull-requests` take the same `limit`/`offset`.

`data` stays a list. `meta.pagination` is `{ "limit", "offset", "total", "returned" }`, where `total` counts all items matching the filters.

Not implemented: sorting options and free-text search.

---

## GET /analyses/{analysisId}

Returns

Analysis Summary

Repository

Status

Started

Completed

Confidence

---

## POST /analyses/{analysisId}/rerun

Creates a brand-new Analysis.

Previous Analysis remains unchanged.

Events

AnalysisStarted

---

# Blast Radius APIs

---

## GET /analyses/{analysisId}/blast-radius

Returns

Affected Files

Affected Symbols

Affected Modules

Affected Tests

Dependency Depth

---

# Dependency Graph APIs

---

## GET /analyses/{analysisId}/graph

Returns graph metadata.

---

## GET /analyses/{analysisId}/graph/nodes

Returns nodes.

Supports pagination.

---

## GET /analyses/{analysisId}/graph/edges

Returns graph edges.

---

# Test APIs

---

## GET /analyses/{analysisId}/tests

Returns

Selected Tests

Execution Status

Duration

Coverage

---

## POST /analyses/{analysisId}/tests/run

Re-run selected tests.

---

## GET /analyses/{analysisId}/tests/flaky

Quarantined (flaky) tests of the analysis' repository (F-11). Tenant-scoped.
Scores every test from its execution history; see `docs/FLAKY_TESTS.md`.

Query (all optional): `window` (2-200, default 20), `minComparable` (default 3), `threshold` (0-1, default 0.2).

Returns

```json
{
  "repository_id": "uuid",
  "window": 20, "min_comparable": 3, "threshold": 0.2,
  "insufficient_history_count": 4,
  "quarantined": [
    {"test_path": "tests/test_x.py", "test_name": "test_x", "score": 0.5,
     "comparable": 6, "flips": 3, "samples_considered": 8,
     "quarantined": true, "last_status": "flaky"}
  ]
}
```

Sorted by score (descending), then path. Tests with fewer than `minComparable`
comparable observations are never listed (counted in `insufficient_history_count`).

The run result (`GET .../tests/run`-style payloads) also carries `flaky` (count)
and `flaky_tests` (ids) when the worker reran failures; both are `0` / `[]`
unless `WORKER_TEST_RERUNS > 0`.

---

# Confidence APIs

---

## GET /analyses/{analysisId}/confidence

Returns

Confidence Score (`confidence_score`, 0-100)

Score Kind (`score_kind`): how to interpret the score. Currently always
`"heuristic_uncalibrated"`: the score is a heuristic built from fixed
penalties, NOT a calibrated probability. The field is additive; the value of
`confidence_score` is unchanged. Clients should display the label alongside
the number. The value will become `"calibrated"` only once calibration (CA-*)
ships behind the feature flag (VD-07). This is the only endpoint that returns
the score.

Risk Level

Evidence

Recommendations

---

# Intent APIs

Read and manage what a change is supposed to do: criteria with provenance, versioned snapshots and human confirmation (IN-08). Base path `/analyses/{analysisId}/intent`.

Conventions

- Auth and tenancy as everywhere (`X-Radius-Organization-Id`, `X-Radius-API-Key`). Unlike other analysis routes, an analysis that belongs to another organization is indistinguishable from a missing one: **404 `ANALYSIS_NOT_FOUND`** (never 403), so ids cannot be probed across tenants. Missing credentials stay 403.
- Requests use camelCase and reject unknown fields; responses use snake_case (like analyses). Pydantic shape errors (missing field, wrong type, unknown field) return FastAPI's default 422; domain validation errors use the envelope with the codes below.
- Intent text is untrusted data. It is sanitized before storage (`radius_shared.llm_guard.sanitize_untrusted`: hidden/bidi/control characters, HTML comments and secrets removed), never executed, bounded (64 KiB UTF-8 per source, 2000 characters per criterion, 256 KiB per request body) and returned as JSON strings. Responses carry `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`. **Clients must escape the text before rendering it as HTML.**
- Optimistic concurrency: reads return an `ETag` (strong; changes on a new snapshot version and on any criterion decision). Writes accept `If-Match` (an ETag, a list, or `*`); a mismatch returns **409 `INTENT_STALE`**. Without `If-Match` the write applies to the latest snapshot.
- Audit actor: `org:<organizationId>`. Send `X-Radius-Actor: <label>` (`[A-Za-z0-9_.@:+-]{1,128}`, for example the dashboard user) to record `org:<id>/<label>`. The label is not verified by Radius.
- Logs contain ids, lengths and a SHA-256 prefix of intent text, never the text.
- Sources can now also come from GitHub (IN-02): `GET .../intent` lists them with these `source_id`s and kinds: `pr-title` (`pr_title`), `pr-body` (`pr_body`), `intent.yml` (`spec_file`), `commits` (`commit_message`, one source, a section per commit), `issue:<n>` / `issue:<owner>:<repo>:<n>` (`issue`) and `issue-comments:<n>` (`comment`, opt-in). `truncated` and `suspicious_content_removed` describe ingestion (64 KiB cap; hidden content removed). A source submitted here under `pr-title`, `pr-body` or `intent.yml` is replaced by GitHub's value on the next ingestion; use another `sourceId` to keep both. The agent prompt (`agent-prompt`) and manual criteria are never touched by ingestion. A missing or forbidden GitHub source is simply absent from the list (the reason is in the worker's `Intent ingestion` log record).

Error codes (in addition to the table below)

| Status | Code | When |
|---|---|---|
| 404 | `ANALYSIS_NOT_FOUND` | unknown analysis or another organization's |
| 404 | `INTENT_NOT_FOUND` | no snapshot yet (the dashboard empty state) |
| 404 | `INTENT_SNAPSHOT_NOT_FOUND`, `CRITERION_NOT_FOUND` | unknown snapshot / criterion |
| 409 | `INTENT_STALE` | `If-Match` does not match the current ETag |
| 409 | `ILLEGAL_STATE_TRANSITION` | for example confirming a rejected criterion |
| 409 | `INTENT_NO_SOURCES` | rebuild before any source was submitted |
| 409 | `DUPLICATE_CRITERION` | manual text equals a `.radius/intent.yml` criterion |
| 409 | `INTENT_BUILD_CONFLICT` | concurrent builds exhausted their retries; retry |
| 422 | `INTENT_SPEC_INVALID` | `.radius/intent.yml` errors, message lists `line N: ...` |
| 422 | `INTENT_SOURCE_TOO_LARGE`, `PAYLOAD_TOO_LARGE`, `INTENT_TEXT_TOO_LONG` | size limits |
| 422 | `INTENT_SOURCE_EMPTY`, `INTENT_TEXT_EMPTY`, `INTENT_SOURCE_ID_INVALID`, `INTENT_SNAPSHOT_REF_INVALID`, `INTENT_ACTOR_INVALID`, `INTENT_TOO_MANY_SOURCES`, `INTENT_SOURCE_KIND_NOT_ALLOWED` | other validation |

---

## GET /analyses/{analysisId}/verdict-v2

Verdict v2 alpha (DEC-027), behind `RADIUS_FEATURE_VERDICT_V2` (`off` default,
`shadow`, `on`). The route is listed in OpenAPI only while the flag is not `off`.
`/analyses/{analysisId}/verdict` is an undocumented alias of the same handler.
Design: `docs/research/design/VERDICT_V2_SLICE.md`; payload schema:
`docs/research/design/verdict_v2.schema.json`.

Contract 4 (`contract_version` `verdict-v2-contract-4`, all additions optional): top-level `alpha` (always `true`), `calibrated` (always `false`), `evidence_basis` (`static_only`) and `presentation` (`verdict_label`, `state_labels`, `legend`, `disclaimer`, `summary_text`: the user-facing wording, where internal `proven` reads SUPPORTED and `verified` reads "Supported by static evidence (alpha)"; clients should show these instead of the raw enum values); `summary.author_hint_criteria`; per criterion `provenance` and `hints[]` (`kind`, `value`, `provenance`, one of `author_pr_body | author_head_spec | base_spec | human_confirmed | llm_proposed`), and the flag and reason code `author_supplied_hint`. Enum values and existing fields are unchanged. See `docs/security/VERDICT_V2_THREAT_MODEL.md`.

Contract 5 (`contract_version` `verdict-v2-contract-5`, all additions optional, only present with `RADIUS_FEATURE_MUTATION`, DEC-035): per evidence item `basis` (`static` | `mutation`), `d_mut`, `d_mut_lcb` (the Wilson lower bound used as `d_eff`), `mutation_n`, `mutation_killed`; per criterion `evidence_basis` (`static_only` | `mutation_measured` | `mutation_partial`) and `mutation` (`n_mutants`, `killed`, `d_union`, `d_union_lcb`, `tests_measured`, `tests_total`, `survivors[]` with `mutant_id`, `path`, `line`, `operator`, `excluded`, `d_reach` always `null` with `d_reach_reason`; with `RADIUS_MUTATION_STAGE2` and a link gap also `link_gaps[]` and `link_gap_tests[]`, DEC-036); top-level `mutation` (with stage 2 also `stage2`) (run summary: `status`, `reason`, `generated`, `sampled`, `decided`, `killed`, `skipped_for_budget`, `cache_hits`, `ladder`); the flag `mutation_measured`; and the one widened value: top-level and `summary.evidence_basis` may be `static_and_mutation` (at least one criterion mutation-measured). With the flag off none of these fields appears and `evidence_basis` stays `static_only`. A measurement is a bounded sample, not a proof; `survivors` paths are untrusted text.

### Responses

| Status | When |
| --- | --- |
| 200 | A verdict was computed. Envelope `{ success, data }`; `ETag` header (strong, over the payload). `If-None-Match` with that tag returns 304. |
| 404 | `meta.reason = "disabled"` when the flag is off (nothing is read). `error.code = ANALYSIS_NOT_FOUND` for an unknown analysis **or an analysis of another organization** (indistinguishable). `meta.reason = "not_computed"` when no verdict exists yet. |
| 403 | Missing or invalid organization credentials. |

`data` (abridged; unknown fields must be ignored by clients):

```json
{
  "verdict_version": 2, "algo_version": "verdict-v2-alpha-1", "profile": "alpha-static",
  "mode": "on", "status": "ok", "analysis_id": "...", "head_sha": "<40 hex>", "revision": 2,
  "computed_at": "2026-11-02T10:16:04Z",
  "verdict": "insufficient_evidence", "pending": false,
  "reasons": [{"code": "unproven_intent_mass", "rule_id": "R2b", "detail": "..."}],
  "score": null, "score_kind": "none", "trust_probability": null,
  "summary": {"criteria_total": 4, "proven": 1, "weak": 1, "unevidenced": 2,
              "contradicted": 0, "excluded": 0, "uim": 0.75, "intent_coverage": 1.0,
              "tamper": {"critical": 0, "high": 0, "medium": 0, "low": 0},
              "evidence_basis": "static_only"},
  "criteria": [{"criterion_id": "...", "text": "UNTRUSTED", "state": "weak", "S": 0.432,
                "S_raw": 0.432, "weight": 1.0, "flags": ["static_only"], "reasons": [],
                "best_link": {"symbol_id": "...", "l_cs": 1.0, "l_st": 0.9, "r_ct": 1.0},
                "items": [{"evidence_id": "ev_...", "test_id": "...", "outcome": "passed",
                           "a_static": 1.0, "d_eff": 0.6, "i": 0.8, "f": 1.0, "q": 0.48,
                           "l": 0.9, "term": 0.432, "status": "counted"}]}],
  "tamper_findings": [], "unlinked_symbols": [], "next_actions": [],
  "justification": {"schema": "verdict-v2-justification-1", "decided_by": "R2b", "rules": []},
  "v1": {"verification_status": "insufficient_evidence", "confidence_score": 31.0,
         "score_kind": "heuristic_uncalibrated", "risk_level": "high"},
  "dashboard_url": null, "error": null
}
```

Honesty rules:

- `verdict` is one of `verified`, `failed`, `insufficient_evidence`, `needs_review`, or
  `null` when `status` is `error` or `skipped` (then `error = {code, fallback}` and
  `criteria` is empty; the stored error detail is never served).
- v2 has no number: `score` is always `null`, `score_kind` always `"none"` and
  `trust_probability` stays `null` until calibration exists. The only score in the payload
  is the `v1` block, copied from the v1 report with its own `score_kind`
  (`heuristic_uncalibrated`). `evidence_basis` is `static_only`: assertion strength read
  from test code, no mutation testing.
- Criterion `text`, test ids, tamper reasons and snippets derive from PR content: they are
  JSON-escaped and clients must render them as text only.
- The v1 route `GET /analyses/{analysisId}/confidence` and its DTO are unchanged and keep
  being computed and served with the flag in any state.
- No sub-resources: the design defines none, criteria are inside `data.criteria`.

Republish after CI: when the flag is not `off`, `POST /analyses/{analysisId}/tests/results`
also upserts one row into the `verdict_v2_requests` outbox (replays collapse; no network
call, the API holds no GitHub credentials). The worker recomputes and updates the Check Run
and PR comment in place.

## GET /analyses/{analysisId}/intent

Latest snapshot. Header `ETag`.

    {
      "success": true,
      "data": {
        "id": "7c0e...", "analysis_id": "a951...", "version": 2,
        "parent_snapshot_id": "52fd...", "created_at": "2026-11-02T10:00:00Z",
        "criteria_count": 2, "state_counts": {"confirmed": 1, "proposed": 1},
        "source_count": 1, "etag": "\"3f9a...\"",
        "criteria": [{
          "id": "crit_9b1c...", "text": "Users must be able to reset their password",
          "origin": {"method": "deterministic", "extractor_version": "det-extract-v1",
                     "source_kind": "pr_body", "source_id": "pr-body",
                     "source_hash": "e3b0...", "retrieved_at": "2026-11-02T10:00:00Z"},
          "span": {"source_id": "pr-body", "start": 24, "end": 67},
          "weight": 1.0, "testability": "behavioral_testable",
          "testability_rationale": "Describes an observable behavior ... [testability-rules-v1; confidence=medium; rules=...]",
          "state": "confirmed", "hints": {"paths": [], "tests": [], "label": null}
        }],
        "sources": [{"kind": "pr_body", "source_id": "pr-body", "raw_text_hash": "e3b0...",
                     "length": 98, "truncated": false, "suspicious_content_removed": false,
                     "fetched_at": "2026-11-02T10:00:00Z"}]
      },
      "meta": {}
    }

`state` is one of `proposed`, `confirmed`, `rejected`, `edited`, `needs_reconfirmation`, `orphaned`. `origin.method` is `deterministic`, `llm` or `human`. A span indexes into the stored (sanitized) text of its source: fetch it with `GET .../intent/sources`.

`testability` is one of `behavioral_testable`, `structural_checkable`, `non_functional_measurable`, `subjective_or_vague`, `untestable_external` (or `unrated` if the rater failed for that criterion); `testability_rationale` explains the rule-based rating and is set whenever the criterion was rated. Ratings are deterministic (no LLM) and are computed when the snapshot is built. `origin.method = "llm"` criteria are proposals only: they exist only when the deployment enabled LLM extraction (`RADIUS_LLM_INTENT_ENABLED`) and the organization is allow-listed, they always start as `proposed`, and a human must confirm them.

## GET /analyses/{analysisId}/intent/snapshots

History, newest first, summaries only (`id`, `version`, `parent_snapshot_id`, `created_at`, `criteria_count`, `state_counts`, `source_count`). Query `limit` (1-100, default 20) and `cursor` (versions below it); `meta.nextCursor` is the cursor of the next page or `null`.

## GET /analyses/{analysisId}/intent/snapshots/{snapshotId}

One snapshot (same shape as the latest). 404 when it belongs to another analysis.

## GET /analyses/{analysisId}/intent/diff?from=&to=

`from` / `to` are snapshot ids or version numbers. Returns `added`, `removed`, `changed` (with `changed_fields`), `state_changed`, `moved` and `sources_added|removed|changed`.

## GET /analyses/{analysisId}/intent/sources

Current sources with their sanitized `text` (for highlighting spans).

## POST /analyses/{analysisId}/intent/sources

Submit or replace a source and rebuild.

    {"kind": "spec_file", "sourceId": "intent.yml",
     "text": "version: 1\ncriteria:\n  - text: \"Users can log in\"\n"}

`kind`: `agent_prompt`, `spec_file` (content of `.radius/intent.yml`), `pr_body`, `pr_title`, `issue`. `sourceId` is optional (`[A-Za-z0-9_.:-]{1,64}`, default per kind); the same kind and id replaces the earlier text, other ids add sources (at most 50 per analysis). Returns 201 when a new snapshot version was created and 200 when the criteria did not change (`created: false`; resubmitting identical text is a no-op). The response has `snapshot`, `created`, `report` (build diagnostics, carry-over events) and `sanitization` (`removed` / `flagged` finding codes; flagged findings such as `injection_phrase` are advisory, the text is stored inert). Human decisions carry over to the new version per the snapshot rules in `packages/intent/README.md`.

A bad `.radius/intent.yml` returns 422 (line numbers refer to the submitted text):

    {"success": false, "error": {"code": "INTENT_SPEC_INVALID",
      "message": "Invalid .radius/intent.yml: line 4: weight must be a number in (0, 1] [spec_invalid_weight]"}}

## POST /analyses/{analysisId}/intent/rebuild

Re-run extraction over the stored sources. Idempotent (`created: false` when nothing changed). 409 `INTENT_NO_SOURCES` when empty.

## PATCH /analyses/{analysisId}/intent/criteria/{criterionId}

    {"action": "confirm"}
    {"action": "reject", "reason": "out of scope"}
    {"action": "reopen"}
    {"action": "edit", "text": "Users must reset their password within 1 hour"}

Applies the domain state machine to the criterion of the latest snapshot and appends an audit row (actor, time, reason). `edit` keeps the criterion id, span and origin and sets `state: edited`. `text` is required for `edit` and rejected otherwise. Weight edits are not supported yet (unknown field, 422). Returns `criterion`, `snapshot_id`, `snapshot_version` and the new `etag`.

## POST /analyses/{analysisId}/intent/criteria

    {"text": "Audit logs are kept for 90 days", "reason": "from the design review"}

Adds a human-authored criterion (`origin.method = human`, source kind `comment`), confirmed on creation. It is stored as a source, so it survives rebuilds and wins over an identical extracted statement. 201 when new, 200 when the same text already exists (idempotent).

## GET /analyses/{analysisId}/intent/criteria/{criterionId}/history

Audit trail across all snapshots, oldest first: `snapshot_id`, `snapshot_version`, `old_state`, `new_state`, `actor`, `changed_at`, `old_text`, `new_text`, `reason`. System carry-over rows have actor `system:intent-snapshots`.

---

# Dashboard APIs

---

## GET /dashboard

Returns

Repository Count

Recent Analyses

Average Confidence

Recent Failures

Repository Activity

---

# GitHub Webhooks

---

## POST /webhooks/github

Purpose

Receive GitHub Events.

Authentication

GitHub Signature Validation

Supported Events

Push

Pull Request

Installation

Repository

Ping

Behavior notes

pull_request opened / reopened / synchronize / ready_for_review (non-draft) start or reuse an analysis for the head SHA.

pull_request closed (merged or not) responds 202 with ignored true and cancelledAnalysisIds: the analyses that were queued but not started are cancelled (analysis status cancelled). Running analyses are never cancelled. Reopening starts a new analysis.

The default branch comes from the delivery (repository.default_branch, else pull_request.base.repo.default_branch). Installation payloads do not carry it, so repositories connected by installation / installation_repositories store a provisional main until the first push or pull_request delivery corrects it.

installation deleted: the organization's installation is marked deleted, all its repositories are disconnected (status disconnected, history kept) and their queued analyses are cancelled. installation suspend / unsuspend toggle a suspended state (repositories stay connected). installation_repositories removed disconnects only the listed repositories of the delivering organization; added reconnects them. A removal for an installation Radius does not know responds 202 ignored (ignoredReason unknown_installation), not 4xx.

push and pull_request deliveries for a disconnected repository or a suspended/deleted installation respond 202 with ignored true and ignoredReason (repository_disconnected, installation_suspended, installation_deleted); nothing is created or queued.

Intent capture (IN-02, best-effort, no GitHub calls from the API): the pull_request payload fields title and body are stored as the intent sources pr-title and pr-body of the analysis started by opened / reopened / synchronize / ready_for_review (skipped if the payload has no body key). pull_request edited still answers ignored true and starts no analysis, but refreshes pr-title / pr-body of the PR's latest analysis. issues edited (ignored true) refreshes the stored text of that issue in the latest analysis of recent PRs of the same repository that already link it. A new intent snapshot version is created only when the text actually changed. A failure in this step never changes the response. issues deliveries for a suspended/deleted installation or a disconnected repository respond with ignoredReason as above. Linked issues, commit messages and .radius/intent.yml are fetched by the worker (see packages/intent/README.md, Source ingestion from GitHub).

Response data fields: ignoredReason (string or null),  deliveryId, event, action, ignored, repositoryId, pullRequestId, analysisId, cancelledAnalysisIds (array, empty unless something was cancelled).

Events Produced

RepositoryUpdated

AnalysisStarted

---

# Organization APIs

---

## GET /organizations

---

## GET /organizations/{id}

---

## POST /organizations

---

## PATCH /organizations/{id}

---

# Pagination

Cursor Based

{
  "items": [],
  "nextCursor": "...",
  "previousCursor": "..."
}

---

# Filtering

Supported

Repository

Branch

Confidence

Status

Date

Risk

Author

---

# Sorting

createdAt

updatedAt

confidence

risk

duration

---

# Error Codes

REPOSITORY_NOT_FOUND

PULL_REQUEST_NOT_FOUND

ANALYSIS_NOT_FOUND

INVALID_GITHUB_SIGNATURE

INTENT_NOT_FOUND

INTENT_STALE

ILLEGAL_STATE_TRANSITION

INTENT_SPEC_INVALID

ACCESS_DENIED

VALIDATION_ERROR

INTERNAL_ERROR

---

# HTTP Status Codes

200 OK

201 Created

202 Accepted

204 No Content

400 Bad Request

401 Unauthorized

403 Forbidden

404 Not Found

409 Conflict

422 Validation Error

500 Internal Server Error

---

# Idempotency

Repository creation

Idempotent

Webhook processing

Idempotent

Analysis rerun

Not idempotent

Repository synchronization

Idempotent

---

# Versioning

All APIs are versioned.

/api/v1

Breaking changes require

/api/v2

---

# OpenAPI

Every endpoint must be represented in the generated OpenAPI specification.

Swagger documentation should be generated automatically from the implementation.

---

# Summary

These contracts define the public interface of Radius.

The frontend, CLI, GitHub integration, and future SDKs should all rely on these contracts rather than implementation details.

## Machine-readable contract and stability

The generated OpenAPI 3.1 document is [`api/openapi.json`](api/openapi.json); regenerate it with `python scripts/export_openapi.py`. Stability levels, the breaking-change definition and the deprecation policy are in [`api/STABILITY.md`](api/STABILITY.md). A typed Python client for the stable routes lives in [`clients/python`](../clients/python/README.md).

## API keys (`/api/v1/api-keys`)

Managed API key administration. Every route needs the `admin` scope and only ever sees the caller's organization (`X-Radius-Organization-Id`). Keys look like `rdk_<8 hex>_<secret>`; the secret is returned once and cannot be retrieved later. See `docs/security/API_KEYS.md`.

| Method and path | Purpose | Success |
|---|---|---|
| `POST /api-keys` | Body `{name, scopes[], expires_at?}`. Create a key. | 201 `{key, token}` |
| `GET /api-keys` | List keys (prefix, scopes, expiry, revoked, `last_used_at`; never the secret). | 200 list |
| `POST /api-keys/{id}/rotate` | Body `{overlap_seconds?}` (default 86400, max 30 days). New key with the same name and scopes; the old key keeps working until the overlap ends. | 201 `{key, token, replaced}` |
| `DELETE /api-keys/{id}` | Revoke immediately (idempotent). | 200 key |
| `GET /api-keys/audit` | Create, rotate and revoke events with the acting key or `legacy-env-key`. | 200 list |

Errors: 403 for missing or insufficient credentials (the same message for unknown, expired, revoked and wrong-organization keys), 404 for a key id from another organization, 422 for invalid scopes, past expiry, bad overlap, or when `RADIUS_API_KEY_PEPPER` is unset.

Existing routes now also require a scope: `read` for GET, `write` for other mutations, `ci-upload` for `POST /analyses/{id}/tests/results` and `POST /coverage`. The GitHub webhook keeps its own HMAC auth.
