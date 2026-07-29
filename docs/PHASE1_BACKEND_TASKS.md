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
- Parser foundation with source discovery, language detection, parser registry, parse service, and tests.

## In Progress

- 30% to 50% foundation:
  - Dependency graph domain contracts and graph builder service.
  - Git change analyzer for deterministic changed-file extraction.
  - Full validation of all backend slices built so far.

## Pending

- Repository local clone/checkout adapter and GitHub webhook/API integration.
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

## 30% to 50% Completion Plan

The next milestone should make Radius capable of turning parsed source metadata
and git diffs into deterministic graph/change evidence:

1. Build the graph package foundation.
   - Add graph nodes, edges, graph snapshots, node/edge types, and identifiers.
   - Add DTOs for graph build requests and graph snapshot responses.
   - Add a graph builder service that consumes parser output and creates file,
     symbol, import, and export relationships.
   - Add an in-memory traversal adapter for reverse dependency lookup.
   - Add tests for graph validation, builder behavior, and traversal.
2. Build the git change analyzer foundation.
   - Add a deterministic parser for `git diff --numstat --name-status` style
     output or equivalent normalized lines.
   - Map added, modified, deleted, and renamed files into the existing
     `ChangedFile` domain model.
   - Add a service that records changed files through `AnalysisApplicationService`
     compatible commands.
   - Add tests for additions, modifications, deletions, renames, binary files,
     and malformed input.
3. Validate the full backend foundation.
   - Run focused package tests for graph and analysis.
   - Run `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build`.
   - Review implemented docs versus code and fix any mismatch before pushing.

## 50% to 80% Draft Plan

After the 50% milestone is validated, the next phase should connect evidence
into an executable deterministic pipeline:

1. Implement blast-radius computation over the graph package.
2. Implement test discovery and deterministic test selection contracts.
3. Implement confidence scoring and evidence aggregation contracts.
4. Add worker orchestration for queued analysis execution.
5. Add backend API routes for repository, analysis, graph, blast-radius, tests,
   and confidence responses.
6. Add end-to-end backend tests that exercise repository metadata, analysis
   creation, changed-file recording, graph construction, blast-radius summary,
   test summary, and confidence report persistence.
