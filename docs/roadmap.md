# Roadmap

# 10_Roadmap.md

# Radius Roadmap

**Project:** Radius

**Version:** 1.0

---

# Vision

Build Radius into an AI-native Software Verification Platform that helps engineering teams answer one question:

> **"Is this Pull Request safe to merge?"**

The roadmap is divided into incremental milestones. Each milestone should deliver a usable improvement to the product.

---

# Phase 1 — Foundation

## Goal

Build the deterministic verification engine.

### Deliverables

- Monorepo setup
- Authentication
- GitHub App integration
- Repository synchronization
- Database
- Dashboard skeleton

### Success Criteria

- User can connect a GitHub repository.
- Repository metadata is synchronized.
- Dashboard displays connected repositories.

---

# Phase 2 — Repository Intelligence

## Goal

Understand repository structure.

### Deliverables

- Tree-sitter integration
- AST extraction
- Symbol extraction
- Import/export analysis
- Metadata storage

### Success Criteria

- Radius understands repository structure.
- Symbols and dependencies are extracted successfully.

---

# Phase 3 — Dependency Graph

## Goal

Build repository knowledge graph.

### Deliverables

- File graph
- Symbol graph
- Dependency resolution
- Graph traversal
- Graph persistence

### Success Criteria

- Repository dependencies are represented accurately.
- Graph updates incrementally after code changes.

---

# Phase 4 — Change Analysis

## Goal

Understand Pull Request impact.

### Deliverables

- Git diff analyzer
- Changed symbol detection
- Blast radius computation
- Dependency depth analysis

### Success Criteria

- Radius identifies all affected files and symbols.
- Blast radius is generated for every analysis.

---

# Phase 5 — Test Intelligence

## Goal

Run only relevant tests.

### Deliverables

- Test discovery
- Test mapping
- Test selection
- Test execution
- Coverage collection

### Success Criteria

- Relevant tests are selected automatically.
- Test execution results are linked to analyses.

---

# Phase 6 — Confidence Engine

## Goal

Generate explainable verification reports.

### Deliverables

- Confidence scoring
- Evidence aggregation
- Risk classification
- Recommendations
- Confidence dashboard

### Success Criteria

- Every analysis produces a confidence report.
- Confidence score includes supporting evidence.

---

# Phase 7 — Developer Experience

## Goal

Create a polished user experience.

### Deliverables

- Analysis history
- Search and filters
- Interactive dependency graph
- Blast radius visualization
- Performance improvements

### Success Criteria

- Developers can easily explore analysis results.
- Dashboard is responsive and intuitive.

---

# Future Roadmap

The following features are intentionally outside Phase 1.

## AI

- AI-generated test cases
- AI risk explanations
- AI code review assistance
- AI optimization suggestions

---

## Security

- Security scanning
- Secret detection
- Dependency vulnerability analysis
- CodeQL integration

---

## Enterprise

- Multi-organization support
- RBAC enhancements
- Audit logs
- SSO
- API keys

---

## Integrations

- Slack
- Microsoft Teams
- Jira
- Linear
- VS Code Extension
- CLI

---

## Platform

- Distributed workers
- Queue-based processing
- Neo4j graph database
- Kubernetes deployment
- Horizontal scaling

---

# Milestone Checklist

| Milestone | Status |
|-----------|--------|
| Foundation | ⬜ |
| Repository Intelligence | ⬜ |
| Dependency Graph | ⬜ |
| Change Analysis | ⬜ |
| Test Intelligence | ⬜ |
| Confidence Engine | ⬜ |
| Developer Experience | ⬜ |
| Public Beta | ⬜ |
| v1.0 Release | ⬜ |

---

# Definition of Phase 1 Complete

Phase 1 is complete when Radius can:

- Connect a GitHub repository.
- Detect Pull Request events.
- Synchronize repository changes.
- Parse modified source files.
- Build and update the dependency graph.
- Compute the blast radius.
- Select and execute relevant tests.
- Generate an explainable confidence report.
- Display results in the dashboard.

At this point, Radius provides a complete deterministic software verification workflow and is ready for AI-powered enhancements in future phases.

---

# Guiding Principles

Every feature added to Radius should satisfy at least one of the following:

- Improves repository understanding.
- Improves verification accuracy.
- Improves developer confidence.
- Improves platform scalability.
- Improves user experience.

If a feature does not contribute to these goals, it should be reconsidered.

---

# Conclusion

This roadmap is a living document. As Radius evolves, milestones may be refined, but the guiding vision remains unchanged:

> Build the most reliable and explainable software verification platform that enables engineering teams to ship code with confidence.