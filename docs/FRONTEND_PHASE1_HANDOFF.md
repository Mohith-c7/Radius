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

# Phase 1 Pages And Contents

The frontend should build these pages for Phase 1. The app should open into the
dashboard after authentication; do not build a marketing landing page inside the
product.

Every protected API request must include:

```text
X-Radius-Organization-Id: <organization UUID>
```

Production deployments may also require:

```text
X-Radius-API-Key: <organization API key>
```

---

## 1. Dashboard Overview

Route:

```text
/dashboard
```

Purpose:

Give developers and admins a fast organization-level view of Radius activity.

Primary content:

- Page header with organization name and current environment.
- Summary metrics:
  - Total connected repositories.
  - Total analyses.
  - Running analyses.
  - Failed analyses.
  - Average confidence score if available.
- Recent analyses table:
  - Analysis status.
  - Repository name.
  - Pull request id or number if available.
  - Commit SHA short form.
  - Risk level if confidence exists.
  - Created time.
  - Completed time.
- Recent repository activity:
  - Repository name.
  - Provider.
  - Status.
  - Visibility.
- Failure panel:
  - Recently failed analyses.
  - Error state message if available.
  - Link to the analysis detail page.

Primary actions:

- Connect repository.
- View all repositories.
- View all analyses.
- Open latest analysis.

Current backend data:

```text
GET /api/v1/repositories
GET /api/v1/analyses
GET /api/v1/analyses/{analysisId}/confidence
```

Frontend note:

There is no dedicated `/dashboard` API yet. Build the dashboard by combining
repositories and analyses. Confidence can be loaded lazily for recent completed
analyses.

Required states:

- Loading.
- No repositories connected.
- No analyses yet.
- Partial data unavailable.
- Access denied.
- Backend unavailable.

---

## 2. Repository List

Route:

```text
/repositories
```

Purpose:

Show all repositories connected to the organization.

Primary content:

- Repository table:
  - Repository full name.
  - Owner.
  - Provider.
  - Default branch.
  - Visibility.
  - Connection status.
  - Last known activity if available.
- Repository status badge:
  - Connected.
  - Synchronizing.
  - Failed.
  - Disconnected.
- Empty state when no repositories exist.

Filters:

- Status.
- Visibility.
- Provider.
- Search by repository name or owner.

Primary actions:

- Connect repository.
- Open repository detail.
- Disconnect repository.

Current backend data:

```text
GET /api/v1/repositories
POST /api/v1/repositories
DELETE /api/v1/repositories/{repositoryId}
```

Important rules:

- Disconnect must use a confirmation dialog.
- The confirmation must say historical analyses remain preserved.
- Disconnected repositories should remain visible unless the user filters them out.

---

## 3. Connect Repository

Route:

```text
/repositories/connect
```

Purpose:

Allow an organization admin to connect a GitHub repository to Radius.

Primary content:

- Connect form:
  - Organization id, normally hidden or prefilled from auth context.
  - GitHub repository id.
  - Repository owner.
  - Repository name.
  - Default branch.
  - Clone URL.
  - Visibility.
- Validation messages for required fields.
- Success state after connection.

Primary actions:

- Submit connection.
- Cancel and return to repository list.

Current backend data:

```text
POST /api/v1/repositories
```

Frontend note:

Phase 1 backend does not yet expose a GitHub repository picker. The first
frontend version can use a manual form. A later GitHub App integration can
replace this with a selectable repository list.

Required states:

- Form validation error.
- Repository already connected.
- Access denied.
- Backend unavailable.
- Connection successful.

---

## 4. Repository Detail

Route:

```text
/repositories/:repositoryId
```

Purpose:

Show one repository and its analysis history.

Primary content:

- Repository header:
  - Full name.
  - Provider.
  - Visibility.
  - Status.
  - Default branch.
  - Clone URL.
- Repository metadata panel:
  - Radius repository id.
  - GitHub repository id.
  - Owner.
  - Name.
- Analysis history table:
  - Analysis id.
  - Status.
  - Pull request id.
  - Commit SHA short form.
  - Created time.
  - Completed time.
  - Link to analysis detail.
- Repository health area:
  - Latest failed analysis.
  - Latest completed analysis.
  - Latest confidence score if available.

Tabs:

- Overview.
- Analyses.
- Settings.

Primary actions:

- Open analysis.
- Start manual analysis if the frontend has PR id and commit SHA.
- Disconnect repository.

Current backend data:

```text
GET /api/v1/repositories/{repositoryId}
GET /api/v1/analyses?repositoryId={repositoryId}
POST /api/v1/analyses
DELETE /api/v1/repositories/{repositoryId}
```

Frontend note:

There is no dedicated pull request list endpoint yet. In Phase 1, pull request
information appears through analysis records and webhook-created backend rows.

---

## 5. Analysis List

Route:

```text
/analyses
```

Purpose:

Let users search, filter, and open analysis runs across repositories.

Primary content:

- Analysis table:
  - Status.
  - Repository id or repository display name if locally resolved.
  - Pull request id.
  - Commit SHA short form.
  - Created time.
  - Started time.
  - Completed time.
  - Link to detail page.
- Optional confidence/risk columns for completed analyses.
- Empty state when no analyses exist.

Filters:

- Repository.
- Pull request id.
- Status.
- Date range.
- Risk level if confidence is loaded.

Sorting:

- Created time.
- Completed time.
- Status.
- Risk level if confidence is loaded.

Primary actions:

- Open analysis detail.
- Clear filters.

Current backend data:

```text
GET /api/v1/analyses
GET /api/v1/analyses?repositoryId={repositoryId}
GET /api/v1/analyses?pullRequestId={pullRequestId}
GET /api/v1/analyses?status={status}
GET /api/v1/analyses/{analysisId}/confidence
```

---

## 6. Analysis Detail

Route:

```text
/analyses/:analysisId
```

Purpose:

This is the most important Phase 1 page. It should answer whether the pull
request looks safe to merge.

Primary content:

- Analysis header:
  - Analysis status.
  - Risk level if confidence exists.
  - Confidence score if confidence exists.
  - Repository id.
  - Pull request id.
  - Commit SHA.
  - Created time.
  - Started time.
  - Completed time.
- Status timeline:
  - Pending.
  - Running.
  - Completed.
  - Failed.
  - Cancelled.
- Changed files section:
  - File path.
  - Change type.
  - Additions.
  - Deletions.
- Blast-radius summary section:
  - Affected files.
  - Affected symbols.
  - Affected modules.
  - Affected tests.
  - Dependency depth.
- Selected tests section:
  - Selected count.
  - Test path.
  - Test name.
  - Framework.
  - Selection reason.
- Confidence section:
  - Score.
  - Risk level.
  - Summary.
  - Evidence.
  - Recommendations.
- Graph summary:
  - Node count.
  - Edge count.
  - Link to graph view.

Recommended layout:

- Top status/risk summary.
- Then tabs or anchored sections:
  - Overview.
  - Changed Files.
  - Blast Radius.
  - Tests.
  - Confidence.
  - Graph.

Primary actions:

- Re-run analysis.
- Open graph view.
- Open repository detail.
- Copy analysis id.
- Copy commit SHA.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}
GET /api/v1/analyses/{analysisId}/blast-radius
GET /api/v1/analyses/{analysisId}/tests
GET /api/v1/analyses/{analysisId}/confidence
GET /api/v1/analyses/{analysisId}/graph
POST /api/v1/analyses/{analysisId}/rerun
```

Important rule:

Completed analyses are immutable. Re-run creates a new analysis instead of
mutating the old one.

---

## 7. Changed Files View

Route:

```text
/analyses/:analysisId/changed-files
```

Purpose:

Give a focused view of the files Radius detected from the pull request diff.

Primary content:

- Changed files table:
  - Path.
  - Change type.
  - Additions.
  - Deletions.
- Summary:
  - Total changed files.
  - Added files.
  - Modified files.
  - Deleted files.
  - Renamed files.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}
```

Frontend note:

Changed files are currently included in the analysis detail response.

---

## 8. Blast Radius View

Route:

```text
/analyses/:analysisId/blast-radius
```

Purpose:

Explain the estimated impact of the pull request.

Primary content:

- Summary cards:
  - Affected files.
  - Affected symbols.
  - Affected modules.
  - Affected tests.
  - Dependency depth.
- Explanation panel:
  - What changed.
  - What Radius believes is affected.
  - Whether the impact is shallow or deep.
- Link back to analysis detail.
- Link to dependency graph.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}/blast-radius
```

Design expectation:

Use dense, scannable layouts. Developers should quickly understand impact depth
and scope.

---

## 9. Dependency Graph View

Route:

```text
/analyses/:analysisId/graph
```

Purpose:

Help developers inspect dependency relationships behind the blast-radius result.

Primary content:

- Graph summary:
  - Node count.
  - Edge count.
  - Graph version.
- Nodes table:
  - Node id.
  - Node type.
  - Label.
  - Path.
- Edges table:
  - Source.
  - Target.
  - Edge type.
- Optional visual graph:
  - Pan.
  - Zoom.
  - Select node.
  - Highlight upstream/downstream relationships.

Filters:

- Node type.
- Edge type.
- File path.
- Search node label.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}/graph
GET /api/v1/analyses/{analysisId}/graph/nodes
GET /api/v1/analyses/{analysisId}/graph/edges
```

Important:

Large graphs must not freeze the UI. Use table pagination, virtualized lists, or
progressive rendering when node/edge counts grow.

---

## 10. Selected Tests View

Route:

```text
/analyses/:analysisId/tests
```

Purpose:

Show which tests Radius selected and why.

Primary content:

- Test selection summary:
  - Selected count.
  - Analysis id.
- Selected tests table:
  - Test name.
  - Test path.
  - Framework.
  - Test type if available.
  - Target path if available.
  - Selection reason.
- Test run plan:
  - Planned command.
  - Selected test paths.
  - Plan status.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}/tests
```

Frontend note:

There is no Phase 1 frontend-triggered test-run endpoint yet. Tests run as part
of backend worker analysis execution.

---

## 11. Confidence Report View

Route:

```text
/analyses/:analysisId/confidence
```

Purpose:

Explain Radius' merge confidence in a way developers can trust.

Primary content:

- Confidence score.
- Risk level.
- Summary.
- Evidence list:
  - Category.
  - Label.
  - Message.
  - Impact.
  - Value if present.
- Recommendations list.
- Test evidence summary:
  - Total tests.
  - Passed.
  - Failed.
  - Skipped.
  - Coverage percentage if available.
- Impact evidence summary:
  - Affected files.
  - Affected symbols.
  - Affected modules.
  - Affected tests.
  - Dependency depth.

Current backend data:

```text
GET /api/v1/analyses/{analysisId}/confidence
```

Critical rule:

Never show a confidence score without evidence. If evidence is missing, show the
report as incomplete.

---

## 12. Repository Settings

Route:

```text
/repositories/:repositoryId/settings
```

Purpose:

Allow admins to inspect and manage repository connection settings.

Primary content:

- Repository identity:
  - Repository id.
  - GitHub repository id.
  - Owner.
  - Name.
  - Clone URL.
- Connection state:
  - Status.
  - Visibility.
  - Provider.
  - Default branch.
- Danger zone:
  - Disconnect repository.
  - Confirmation text explaining historical analyses are preserved.

Current backend data:

```text
GET /api/v1/repositories/{repositoryId}
DELETE /api/v1/repositories/{repositoryId}
```

---

## 13. Not Found And Error Pages

Routes:

```text
/404
/error
```

Purpose:

Handle missing resources and backend/API failures without losing user context.

Must support:

- Repository not found.
- Analysis not found.
- Graph not found.
- Confidence report not generated yet.
- Access denied.
- Backend unavailable.

Content:

- Human-readable title.
- Backend error message if available.
- Resource id if useful.
- Action back to dashboard, repositories, or analyses.

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
