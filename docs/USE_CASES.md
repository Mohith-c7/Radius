# 09_Use_Cases.md

# Use Cases

**Project:** Radius

**Version:** 1.0

---

# Overview

This document defines the functional behavior of Radius from the perspective of its users.

Each use case describes a complete interaction between an actor and the platform.

These use cases serve as the foundation for:

- REST API design
- Frontend workflows
- Database schema
- Backend services
- Acceptance testing

Every implemented feature must correspond to one or more documented use cases.

---

# Actors

## Developer

Primary user of Radius.

Responsibilities

- Connect repositories
- Review analyses
- Inspect blast radius
- Review confidence reports

---

## Organization Admin

Manages organization settings.

Responsibilities

- Connect GitHub
- Manage repositories
- Configure analysis
- Manage members

---

## GitHub

External actor.

Responsibilities

- Send webhooks
- Deliver pull request events
- Provide repository data

---

## Radius Worker

Internal actor.

Responsible for executing long-running analysis workflows.

---

# UC-01 Connect Repository

## Goal

Allow an organization to connect a GitHub repository to Radius.

### Primary Actor

Organization Admin

### Preconditions

- User is authenticated
- GitHub App is installed
- Repository is accessible

### Main Flow

1. User clicks "Connect Repository"
2. Radius retrieves accessible repositories
3. User selects repository
4. Radius validates permissions
5. Repository is registered
6. Initial synchronization begins
7. Repository appears in dashboard

### Alternative Flows

- Repository already connected
- Missing permissions
- GitHub unavailable

### Postconditions

Repository is available for future analyses.

---

# UC-02 Synchronize Repository

## Goal

Keep repository metadata up to date.

### Actor

GitHub

### Trigger

Push event

Repository event

Webhook

### Main Flow

1. GitHub sends webhook
2. Radius verifies signature
3. Repository is synchronized
4. Branch information updated
5. Commit history refreshed

### Output

Repository snapshot.

---

# UC-03 Analyze Pull Request

## Goal

Automatically analyze every pull request.

### Actor

GitHub

### Trigger

Pull Request opened

Pull Request synchronized

### Main Flow

1. Webhook received
2. Repository synchronized
3. Git diff analyzed
4. Changed files identified
5. Parser executed
6. Dependency graph updated
7. Blast radius calculated
8. Tests selected
9. Tests executed
10. Confidence report generated
11. Results stored
12. GitHub Check published

### Postconditions

Analysis completed successfully.

---

# UC-04 View Repository Dashboard

## Goal

Display repository health.

### Actor

Developer

### Main Flow

1. Open repository
2. Load repository overview
3. Display

- Pull Requests
- Recent analyses
- Confidence trends
- Repository statistics

---

# UC-05 View Analysis

## Goal

Inspect one analysis.

### Actor

Developer

### Main Flow

1. Open analysis
2. Display

- Changed files
- Changed symbols
- Dependency graph
- Blast radius
- Selected tests
- Test results
- Confidence score
- Recommendations

---

# UC-06 View Blast Radius

## Goal

Understand impact.

### Actor

Developer

### Main Flow

1. Open Blast Radius tab
2. Radius displays

Affected files

Affected modules

Affected APIs

Affected tests

Dependency depth

### Postconditions

Developer understands change impact.

---

# UC-07 View Dependency Graph

## Goal

Explore repository relationships.

### Actor

Developer

### Main Flow

Display

Nodes

Edges

Imports

Dependencies

References

Provide interactive navigation.

---

# UC-08 Execute Analysis Again

## Goal

Re-run verification.

### Actor

Developer

### Preconditions

Analysis already exists.

### Main Flow

1. Click Re-run
2. New analysis created
3. Previous analysis retained
4. Pipeline executed
5. Dashboard updated

---

# UC-09 Review Confidence Report

## Goal

Understand why Radius produced a confidence score.

### Actor

Developer

### Main Flow

Display

Confidence score

Risk level

Evidence

Recommendations

Test summary

Coverage summary

Every score must include an explanation.

---

# UC-10 Compare Analyses

## Goal

Compare multiple analysis runs.

### Actor

Developer

### Main Flow

Select two analyses.

Display differences.

Confidence

Coverage

Blast Radius

Test Results

Execution Time

---

# UC-11 Search Repository

## Goal

Locate previous analyses.

### Actor

Developer

### Search Filters

Repository

Pull Request

Branch

Author

Confidence

Risk Level

Status

Date

---

# UC-12 Manage Organization

## Goal

Manage organization configuration.

### Actor

Organization Admin

### Capabilities

Invite members

Remove members

Manage repositories

Configure defaults

View organization settings

---

# Business Rules

BR-01

Every Pull Request creates a new Analysis.

---

BR-02

Analyses are immutable after completion.

---

BR-03

Deleting repositories must not delete historical analyses.

---

BR-04

Confidence scores must always include evidence.

---

BR-05

Repository synchronization must occur before analysis.

---

BR-06

Every analysis has exactly one Confidence Report.

---

BR-07

Analyses may execute concurrently.

---

BR-08

Failed analyses remain visible.

---

# Non-Functional Requirements

Analysis should be fault tolerant.

Long-running operations should execute asynchronously.

Historical data must be preserved.

Users should always receive meaningful progress updates.

Failures should not block future analyses.

---

# Future Use Cases

The following are intentionally out of scope for Phase 1.

- AI-generated test creation
- Security verification
- Multi-repository impact analysis
- Slack notifications
- Jira integration
- VS Code extension
- CLI
- Natural language repository search
- Predictive merge risk
- Historical learning

---

# Summary

These use cases define every interaction supported by Phase 1 of Radius.

All APIs, frontend workflows, backend services, and database schemas should trace back to one or more of these documented use cases.

Any new feature added to Radius must first introduce or extend a documented use case before implementation begins.