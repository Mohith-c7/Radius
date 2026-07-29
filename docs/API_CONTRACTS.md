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

List analyses.

Supports

Pagination

Filtering

Sorting

Search

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

# Confidence APIs

---

## GET /analyses/{analysisId}/confidence

Returns

Confidence Score

Risk Level

Evidence

Recommendations

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