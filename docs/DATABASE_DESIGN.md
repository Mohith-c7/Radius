# 08_Database_Design.md

# Database Design

**Project:** Radius

**Version:** 1.0

---

# Overview

This document defines the persistent data model for Radius.

The database stores the long-lived state of the platform, while derived information (such as dependency graphs and confidence calculations) is computed by the application layer.

The database is designed to support:

- Repository management
- Pull Request tracking
- Analysis history
- Test execution history
- Confidence reports
- Future scalability

PostgreSQL is the primary database for Phase 1.

---

# Design Principles

- PostgreSQL is the source of truth.
- Normalize data wherever practical.
- Store immutable analysis history.
- Avoid storing derived data unless it improves performance.
- Use UUIDs as primary keys.
- Use foreign keys for all relationships.
- Index frequently queried columns.
- Every table includes `created_at` and `updated_at`.

---

# High-Level ER Diagram

```text
Organization
    │
    ├── Users
    │
    └── Repositories
            │
            ├── Branches
            ├── PullRequests
            │       │
            │       └── Analyses
            │               │
            │               ├── ChangedFiles
            │               ├── BlastRadius
            │               ├── TestRuns
            │               └── ConfidenceReports
            │
            └── GraphSnapshots
```

---

# Core Tables

## organizations

Represents a customer organization.

| Column | Type |
|---------|------|
| id | UUID |
| name | VARCHAR |
| github_installation_id | BIGINT |
| created_at | TIMESTAMP |
| updated_at | TIMESTAMP |

---

## users

Represents an authenticated user.

| Column | Type |
|---------|------|
| id | UUID |
| organization_id | UUID |
| github_user_id | BIGINT |
| name | VARCHAR |
| email | VARCHAR |
| role | VARCHAR |
| created_at | TIMESTAMP |
| updated_at | TIMESTAMP |

---

## repositories

Represents a connected Git repository.

| Column | Type |
|---------|------|
| id | UUID |
| organization_id | UUID |
| github_repository_id | BIGINT |
| name | VARCHAR |
| owner | VARCHAR |
| default_branch | VARCHAR |
| clone_url | TEXT |
| visibility | VARCHAR |
| status | VARCHAR |
| created_at | TIMESTAMP |
| updated_at | TIMESTAMP |

---

## branches

Repository branches.

| Column | Type |
|---------|------|
| id | UUID |
| repository_id | UUID |
| name | VARCHAR |
| latest_commit_sha | VARCHAR |
| created_at | TIMESTAMP |
| updated_at | TIMESTAMP |

---

## pull_requests

Represents a GitHub Pull Request.

| Column | Type |
|---------|------|
| id | UUID |
| repository_id | UUID |
| github_pr_number | INTEGER |
| title | TEXT |
| source_branch | VARCHAR |
| target_branch | VARCHAR |
| author | VARCHAR |
| status | VARCHAR |
| opened_at | TIMESTAMP |
| merged_at | TIMESTAMP NULL |

---

## analyses

Represents one verification run.

| Column | Type |
|---------|------|
| id | UUID |
| repository_id | UUID |
| pull_request_id | UUID |
| commit_sha | VARCHAR(40) |
| status | VARCHAR |
| started_at | TIMESTAMP |
| completed_at | TIMESTAMP NULL |
| created_at | TIMESTAMP |

Status values:

- Pending
- Running
- Completed
- Failed
- Cancelled

---

## changed_files

Stores files modified during an analysis.

| Column | Type |
|---------|------|
| id | UUID |
| analysis_id | UUID |
| path | TEXT |
| change_type | VARCHAR |
| additions | INTEGER |
| deletions | INTEGER |

Change types:

- Added
- Modified
- Deleted
- Renamed

---

## graph_snapshots

Represents the dependency graph generated for an analysis.

| Column | Type |
|---------|------|
| id | UUID |
| repository_id | UUID |
| analysis_id | UUID |
| node_count | INTEGER |
| edge_count | INTEGER |
| graph_version | VARCHAR |
| created_at | TIMESTAMP |

> The graph itself is stored externally (file/object storage). This table stores only metadata.

---

## blast_radius

Stores impact analysis results.

| Column | Type |
|---------|------|
| id | UUID |
| analysis_id | UUID |
| affected_files | INTEGER |
| affected_symbols | INTEGER |
| affected_modules | INTEGER |
| affected_tests | INTEGER |
| dependency_depth | INTEGER |

---

## test_runs

Represents executed tests.

| Column | Type |
|---------|------|
| id | UUID |
| analysis_id | UUID |
| framework | VARCHAR |
| total_tests | INTEGER |
| passed | INTEGER |
| failed | INTEGER |
| skipped | INTEGER |
| duration_ms | INTEGER |
| coverage_percent | DECIMAL(5,2) |

---

## confidence_reports

Stores the final verification result.

| Column | Type |
|---------|------|
| id | UUID |
| analysis_id | UUID |
| confidence_score | DECIMAL(5,2) |
| risk_level | VARCHAR |
| summary | TEXT |
| generated_at | TIMESTAMP |

Risk Levels:

- Low
- Medium
- High
- Critical

---

# Relationships

```text
Organization
    1 ─────── * Users

Organization
    1 ─────── * Repositories

Repository
    1 ─────── * Branches

Repository
    1 ─────── * PullRequests

Repository
    1 ─────── * Analyses

PullRequest
    1 ─────── * Analyses

Analysis
    1 ─────── * ChangedFiles

Analysis
    1 ─────── 1 BlastRadius

Analysis
    1 ─────── * TestRuns

Analysis
    1 ─────── 1 ConfidenceReport

Analysis
    1 ─────── 1 GraphSnapshot
```

---

# Index Strategy

The following indexes should exist:

```sql
repositories(github_repository_id)

repositories(organization_id)

pull_requests(repository_id, github_pr_number)

analyses(repository_id)

analyses(pull_request_id)

analyses(commit_sha)

changed_files(analysis_id)

test_runs(analysis_id)

confidence_reports(analysis_id)
```

---

# Immutable Data

The following records must never be modified after creation:

- Analysis
- Changed Files
- Blast Radius
- Test Runs
- Confidence Report
- Graph Snapshot

Historical verification data is preserved permanently.

---

# Mutable Data

The following records may be updated:

- Organization
- User
- Repository
- Branch

---

# Data Retention

Phase 1 retains all analyses.

Future versions may introduce configurable retention policies.

No historical analysis should be deleted automatically.

---

# Future Expansion

The schema is designed to support future capabilities without breaking existing data.

Planned additions include:

- AI-generated tests
- Security findings
- Neo4j graph references
- Historical confidence trends
- Repository metrics
- Deployment verification
- Multi-repository analysis

These will be added through new tables rather than modifying existing ones.

---

# Naming Conventions

- Table names use `snake_case` and are plural.
- Primary keys use `id`.
- Foreign keys use `<entity>_id`.
- Timestamp columns use UTC.
- Enumerations should be implemented using PostgreSQL ENUM types where appropriate.

---

# Summary

The Radius database is designed to preserve a complete, immutable history of software verification while supporting efficient querying and future platform expansion. It serves as the persistent foundation for repository management, analysis tracking, testing, and confidence reporting.