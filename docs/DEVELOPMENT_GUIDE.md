# 09_Development_Guide.md

# Development Guide

**Project:** Radius

**Version:** 1.0

---

# Purpose

This document defines the engineering workflow for developing Radius.

It establishes the project structure, coding workflow, branching strategy, quality standards, and development practices to ensure consistency across contributors.

---

# Development Principles

Every contribution to Radius should follow these principles:

- Build small, testable features.
- Prefer simple solutions over clever implementations.
- Keep modules independent.
- Write production-ready code.
- Avoid premature optimization.
- Document architectural decisions.
- Never sacrifice maintainability for speed.

---

# Technology Stack

## Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui

---

## Backend

- FastAPI
- Python 3.12+
- SQLAlchemy
- Alembic
- Pydantic

---

## Database

- PostgreSQL

---

## Parsing

- Tree-sitter

---

## Graph Processing

- NetworkX

---

## Authentication

- GitHub OAuth
- GitHub App

---

## Development Tools

- pnpm
- TurboRepo
- Docker
- GitHub Actions
- Ruff
- Black
- Pytest
- ESLint
- Prettier

---

# Repository Workflow

Every new feature should follow the same lifecycle.

```text
Issue

↓

Feature Branch

↓

Implementation

↓

Tests

↓

Pull Request

↓

Review

↓

Merge
```

---

# Branch Strategy

Radius uses trunk-based development with short-lived branches.

## Main

`main` is the protected integration and release branch.

All completed work merges back into `main` through pull requests.

Direct commits to `main` should be reserved for repository setup or explicitly approved maintenance work.

---

## Feature Branches

Feature branches use the `codex/feature/` prefix.

Naming convention:

```text
codex/feature/<area>-<summary>

Examples

codex/feature/repository-github-app

codex/feature/parser-symbol-extraction

codex/feature/analysis-blast-radius
```

---

## Bug Fixes

Bug fixes use the `codex/fix/` prefix.

```text
codex/fix/<area>-<summary>
```

---

## Documentation

Documentation-only work uses the `codex/docs/` prefix.

```text
codex/docs/<summary>
```

---

## Releases

Release stabilization branches are created only when needed.

```text
release/<version>
```

---

## Hotfixes

Urgent production fixes use:

```text
hotfix/<summary>
```

Hotfixes merge back into `main`.

---

# Commit Convention

Follow Conventional Commits.

Examples:

```text
feat(repository): add GitHub repository sync

feat(parser): implement AST extraction

fix(graph): resolve circular dependency traversal

refactor(testing): simplify test discovery

docs(api): update analysis endpoints

test(confidence): add confidence engine tests
```

---

# Pull Request Checklist

Every Pull Request must:

- Build successfully
- Pass all tests
- Follow coding standards
- Include documentation updates if required
- Avoid unrelated changes
- Include a clear description

---

# Coding Standards

## General

- Write readable code.
- Keep functions short.
- Avoid duplicate logic.
- Use descriptive names.
- Prefer composition over inheritance.

---

## Backend

- Use dependency injection.
- Validate all inputs.
- Use typed models.
- Never expose database models directly.
- Separate application and infrastructure layers.

---

## Frontend

- Use reusable components.
- Keep components focused.
- Separate UI from data fetching.
- Avoid unnecessary state.

---

# Testing Strategy

Every feature requires:

- Unit Tests
- Integration Tests (where applicable)

Coverage targets:

| Type | Target |
|-------|--------|
| Backend | ≥90% |
| Frontend | ≥80% |
| Critical Services | 100% |

---

# Code Review Guidelines

Reviewers should verify:

- Correctness
- Readability
- Performance
- Security
- Test coverage
- Architectural consistency

Questions to ask:

- Is this the simplest solution?
- Does it follow the module boundaries?
- Can this be extended later?
- Is the code well-tested?

---

# Error Handling

- Never ignore exceptions.
- Return meaningful error messages.
- Log unexpected failures.
- Avoid exposing internal implementation details.

---

# Logging

Every major operation should log:

- Repository synchronization
- Pull Request analysis
- Parser execution
- Graph generation
- Test execution
- Confidence calculation

Use structured logging.

---

# Security Guidelines

- Validate all user input.
- Verify GitHub webhook signatures.
- Never store secrets in code.
- Use environment variables for configuration.
- Apply least-privilege access.

---

# Performance Guidelines

Optimize only after measurement.

Priority:

1. Correctness
2. Readability
3. Maintainability
4. Performance

---

# Definition of Done

A feature is complete when:

- Requirements are implemented.
- Tests pass.
- Documentation is updated.
- Code review is approved.
- No known critical bugs remain.

---

# Development Workflow

Every feature follows this sequence:

```text
Understand Requirement

↓

Design Solution

↓

Implement

↓

Write Tests

↓

Review

↓

Merge

↓

Deploy
```

---

# Summary

Radius is developed through small, incremental, production-quality changes. Every contribution should improve the platform while preserving modularity, maintainability, and long-term scalability.
