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
- Dependency graph foundation with deterministic graph builder, in-memory store/traversal, and tests.
- Git change analyzer foundation with unified diff parsing, git diff provider, analysis service integration, and tests.
- Blast-radius computation over graph reverse dependencies with persisted summary integration.
- Testing foundation with conventional discovery, path-based selection, structured run planning, and tests.
- Confidence foundation with deterministic scoring, evidence, recommendations, in-memory store, and tests.

## In Progress

- API and worker orchestration planning for the final Phase 1 backend spine.

## Pending

- Repository local clone/checkout adapter and GitHub webhook/API integration.
- SQLAlchemy adapters for graph artifacts/test selections/confidence evidence if persistence schema expands.
- API routes for repositories, analyses, blast radius, tests, and confidence.
- Worker orchestration for queued analysis execution.
- End-to-end backend flow from webhook/manual trigger to persisted confidence report.

## Current Completion Estimate

Phase 1 backend foundation is roughly 80% complete for the deterministic core:
workspace, shared primitives, persistence schema, repository contracts, analysis
lifecycle, parser contracts, graph construction, git change extraction,
blast-radius computation, test discovery/selection, and confidence scoring are
implemented and validated. Remaining work is mostly orchestration and exposure:
GitHub/local clone integration, API routes, worker pipeline wiring, and
end-to-end backend flow tests.

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

## 50% to 80% Implementation Plan

After the 50% milestone, the next phase connects evidence into an executable
deterministic pipeline:

1. Implement blast-radius computation over graph reverse dependencies.
   - Map changed files to graph file nodes.
   - Traverse reverse dependencies.
   - Compute affected files, symbols/modules, tests placeholder count, and
     dependency depth.
   - Persist the result through existing analysis blast-radius storage.
2. Implement test discovery and deterministic test selection contracts.
   - Discover tests by conventional paths and filename patterns.
   - Map tests to affected files/modules without executing shell commands yet.
   - Keep execution behind an interface for a later worker slice.
3. Implement confidence scoring and evidence aggregation contracts.
   - Score deterministically from blast radius and test summaries.
   - Produce explainable evidence and risk level.
   - Persist final report through the existing database table in a later adapter.
4. Add worker orchestration for queued analysis execution.
5. Add backend API routes for repository, analysis, graph, blast-radius, tests,
   and confidence responses.
6. Add end-to-end backend tests that exercise repository metadata, analysis
   creation, changed-file recording, graph construction, blast-radius summary,
   test summary, and confidence report persistence.
