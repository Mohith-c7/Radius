# Frontend Phase 1 Handoff

Project: Radius

Audience: Frontend developer responsible for the Phase 1 dashboard.

This document defines what the frontend should build for Phase 1 and how it should integrate with backend contracts. It is intentionally implementation-focused and should be kept aligned with `USE_CASES.md`, `API_CONTRACTS.md`, and `PHASE1_SPECIFICATION.md`.

---

# Frontend Responsibility

The frontend is the Presentation Domain for developers and organization admins.

It should:

- Display repository and analysis information clearly.
- Help developers understand pull request impact.
- Explain confidence, risk, and evidence.
- Surface progress and failures without hiding uncertainty.
- Coordinate with backend APIs only through documented contracts.

It must not:

- Contain repository analysis logic.
- Compute dependency graphs.
- Compute blast radius.
- Compute confidence scores.
- Execute tests.
- Access database tables directly.

---

# Phase 1 User Roles

## Developer

Primary user reviewing repository analyses.

Needs to:

- View connected repositories.
- Open a repository dashboard.
- Inspect pull request analyses.
- Review blast radius.
- Review selected tests and test results.
- Review confidence report and recommendations.

## Organization Admin

Admin user managing repository access.

Needs to:

- Connect GitHub repositories.
- View repository connection status.
- Disconnect repositories while preserving historical analyses.

---

# Core UX Principle

Every screen should help answer:

```text
Can this Pull Request be merged safely?
```

Avoid marketing pages in the app. The first screen after login should be an operational dashboard.

---

# Required Screens

## 1. Dashboard Overview

Route suggestion:

```text
/dashboard
```

Purpose:

Show organization-level verification status.

Data from:

```text
GET /api/v1/dashboard
GET /api/v1/repositories
GET /api/v1/analyses
```

Must display:

- Repository count
- Recent analyses
- Average confidence
- Recent failures
- Repository activity

Expected states:

- Loading
- Empty organization
- Normal data
- Partial backend failure
- Authentication required

Primary actions:

- Connect repository
- Open repository
- Open analysis

---

## 2. Repository List

Route suggestion:

```text
/repositories
```

Data from:

```text
GET /api/v1/repositories
POST /api/v1/repositories
DELETE /api/v1/repositories/{repositoryId}
```

Must display:

- Repository name
- Owner
- Provider
- Default branch
- Visibility
- Status
- Last updated time

Filters:

- Provider
- Status
- Visibility

Primary actions:

- Connect repository
- View repository
- Disconnect repository

Important rule:

Disconnecting a repository must communicate that historical analyses remain preserved.

---

## 3. Connect Repository Flow

Route suggestion:

```text
/repositories/connect
```

Purpose:

Allow an organization admin to connect a GitHub repository.

Data from:

```text
POST /api/v1/repositories
```

Flow:

1. Show available GitHub repositories.
2. Let the admin select one repository.
3. Submit connection request.
4. Show synchronization started state.
5. Navigate to repository dashboard when ready.

Required states:

- GitHub App not installed
- Missing permissions
- Repository already connected
- GitHub unavailable
- Synchronization started

---

## 4. Repository Detail

Route suggestion:

```text
/repositories/:repositoryId
```

Data from:

```text
GET /api/v1/repositories/{repositoryId}
GET /api/v1/repositories/{repositoryId}/pull-requests
GET /api/v1/analyses?repositoryId=:repositoryId
```

Must display:

- Repository metadata
- Pull requests
- Recent analyses
- Confidence trends
- Repository statistics

Tabs:

- Overview
- Pull Requests
- Analyses
- Graph
- Settings

---

## 5. Analysis Detail

Route suggestion:

```text
/analyses/:analysisId
```

Data from:

```text
GET /api/v1/analyses/{analysisId}
GET /api/v1/analyses/{analysisId}/blast-radius
GET /api/v1/analyses/{analysisId}/tests
GET /api/v1/analyses/{analysisId}/confidence
GET /api/v1/analyses/{analysisId}/graph
```

Must display:

- Analysis status
- Repository
- Pull request
- Commit SHA
- Start and completion time
- Changed files
- Changed symbols
- Blast radius summary
- Selected tests
- Test results
- Confidence score
- Risk level
- Evidence
- Recommendations

Primary actions:

- Re-run analysis
- Open pull request in GitHub
- Open dependency graph

Important rule:

Completed analyses are immutable. Re-run creates a new analysis instead of mutating the old one.

---

## 6. Blast Radius View

Route suggestion:

```text
/analyses/:analysisId/blast-radius
```

Data from:

```text
GET /api/v1/analyses/{analysisId}/blast-radius
```

Must display:

- Affected files
- Affected symbols
- Affected modules
- Affected APIs
- Affected tests
- Dependency depth

Design expectation:

Use dense, scannable layouts. Developers should quickly understand impact depth and scope.

---

## 7. Dependency Graph View

Route suggestion:

```text
/analyses/:analysisId/graph
```

Data from:

```text
GET /api/v1/analyses/{analysisId}/graph
GET /api/v1/analyses/{analysisId}/graph/nodes
GET /api/v1/analyses/{analysisId}/graph/edges
```

Must display:

- Nodes
- Edges
- Imports
- Dependencies
- References

Expected interactions:

- Pan
- Zoom
- Select node
- Filter by node type
- Filter by relationship type
- Show upstream/downstream dependencies

Important:

Large graphs must not freeze the UI. Use pagination or progressive loading if needed.

---

## 8. Test Results View

Route suggestion:

```text
/analyses/:analysisId/tests
```

Data from:

```text
GET /api/v1/analyses/{analysisId}/tests
POST /api/v1/analyses/{analysisId}/tests/run
```

Must display:

- Selected tests
- Test framework
- Execution status
- Duration
- Passed count
- Failed count
- Skipped count
- Coverage percentage
- Logs

Primary actions:

- Re-run selected tests

---

## 9. Confidence Report View

Route suggestion:

```text
/analyses/:analysisId/confidence
```

Data from:

```text
GET /api/v1/analyses/{analysisId}/confidence
```

Must display:

- Confidence score
- Risk level
- Summary
- Evidence
- Recommendations
- Test summary
- Coverage summary

Critical rule:

Never show a confidence score without evidence. If evidence is missing, show the report as incomplete.

---

## 10. Search And Filters

Route suggestion:

```text
/analyses
```

Data from:

```text
GET /api/v1/analyses
```

Filters:

- Repository
- Pull request
- Branch
- Author
- Confidence
- Risk level
- Status
- Date

Sorting:

- Created at
- Updated at
- Confidence
- Risk
- Duration

---

# API Response Shape

All API responses use this envelope:

```json
{
  "success": true,
  "data": {},
  "meta": {}
}
```

Errors use:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human readable message."
  }
}
```

Frontend code should centralize response parsing and error handling.

---

# Status Handling

Analysis statuses:

- Pending
- Running
- Completed
- Failed
- Cancelled

Repository statuses should support:

- Connected
- Synchronizing
- Failed
- Disconnected

Risk levels:

- Low
- Medium
- High
- Critical

---

# Empty States

Required empty states:

- No repositories connected
- No analyses yet
- No pull requests found
- No affected tests found
- No graph data available
- Confidence report not generated yet

Empty states should provide the next useful action when one exists.

---

# Error States

Required error states:

- Access denied
- Repository not found
- Pull request not found
- Analysis not found
- Invalid GitHub permissions
- GitHub unavailable
- Analysis failed
- Test execution failed

Errors should show the backend-provided message and preserve developer context.

---

# Design Guidance

Radius is an engineering tool, not a marketing surface.

Use:

- Dense but readable layouts
- Tables for repeated operational data
- Tabs for analysis sections
- Badges for status and risk
- Progress indicators for running analyses
- Inline evidence lists for confidence explanations
- Clear destructive-action confirmations

Avoid:

- Marketing hero sections
- Decorative layouts that reduce scannability
- Opaque risk indicators without explanation
- Hiding failed analyses

---

# Phase 1 Frontend Completion Criteria

Frontend Phase 1 is complete when a developer can:

1. View connected repositories.
2. Connect a repository.
3. Open repository details.
4. View pull requests and analyses.
5. Open one analysis.
6. Review changed files and symbols.
7. Review blast radius.
8. Explore dependency graph data.
9. Review selected tests and test results.
10. Review confidence score with evidence.
11. Re-run an analysis.
12. Search and filter analyses.

The frontend does not need to implement AI-generated test workflows, security scanning, Slack/Jira integrations, CLI flows, or natural language search in Phase 1.
