# Phase 1 Backend Task Tracker

This tracker is the backend accountability list for Phase 1 foundation work on
the `develop` branch. Frontend implementation is tracked separately in
`docs/FRONTEND_PHASE1_HANDOFF.md`.

## Branch Policy

- Foundation work is committed directly to `develop`.
- `dev` remains the UAT promotion branch.
- `main` remains the release branch.

## Completed

- Monorepo workspace scaffold with Python packages and dashboard shell.
- Shared configuration, logging, response envelope, and application errors.
- Phase 1 database schema, Alembic migration, SQLAlchemy models, and DB tests.
- Repository domain contracts, DTOs, application service, SQLAlchemy store, and tests.
- Analysis lifecycle contracts, changed-file evidence, blast-radius storage, SQLAlchemy store, and tests.

## In Progress

- Parser foundation:
  - Domain model for source files, symbols, imports, exports, and parse sessions.
  - DTOs for repository parse requests and normalized parser output.
  - Parser service that discovers files and delegates language-specific parsing through interfaces.
  - Filesystem source discovery adapter.
  - Focused tests for domain validation, service orchestration, and filesystem discovery.

## Pending

- Repository local clone/checkout adapter and GitHub webhook/API integration.
- Dependency graph domain contracts and graph builder service.
- Git change analyzer for added, modified, deleted, and renamed files.
- Blast-radius computation engine over graph output.
- Test discovery, selection, execution summaries, and coverage contracts.
- Confidence scoring domain, evidence aggregation, and report persistence.
- API routes for repositories, analyses, blast radius, tests, and confidence.
- Worker orchestration for queued analysis execution.
- End-to-end backend flow from webhook/manual trigger to persisted confidence report.

## Current Completion Estimate

Phase 1 backend foundation is roughly 30% complete after the parser foundation
slice lands: the workspace, shared primitives, persistence schema, repository
contracts, analysis lifecycle, and parser contracts form the first executable
spine for the rest of the deterministic pipeline.
