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
- Real Python AST parser plus lightweight JavaScript/TypeScript parser adapters for imports, symbols, and exports.
- Repository-local module resolver for Python and JS/TS import-to-file dependency edges.
- Improved blast-radius summary counting for affected symbols, modules, and selected tests.
- Local Git clone/fetch/checkout adapter for repository ingestion.
- Worker Phase 1 orchestration for diff analysis, parsing, graph build, blast radius, test selection/planning, and confidence generation.
- API routes for repositories, analyses, blast radius, graph artifacts, selected tests, and confidence reports.
- Durable Phase 1 artifact schema for graph nodes/edges, test selections, run plans, confidence evidence, and analysis jobs.
- SQLAlchemy stores for graph snapshots, test selections/run plans/results, confidence reports/evidence, and analysis jobs.
- Subprocess-backed test runner with timeout, output capture, and confidence input based on actual execution result.
- Worker claim/execute/complete/fail runtime helpers for queued jobs.
- SQL-selectable API storage wiring through `STORAGE_BACKEND=sql`.
- Tenant-scoped API request context for repositories, analyses, graph artifacts, selected tests, and confidence reports.
- API-key enforcement path for production deployments with development-friendly local header context.
- Idempotency-key persistence and replay for repository connect, manual analysis start, rerun, and GitHub webhook delivery handling.
- Repository pull request metadata upsert support in memory and SQLAlchemy stores.
- Signed GitHub webhook endpoint for ping, push branch metadata, and pull request analysis triggers.

## In Progress

- Worker command loading from persisted repository/PR context without test-only local command injection.
- End-to-end persisted webhook-to-confidence execution test.

## Pending

- Worker command loading from persisted repository/PR context without test-only local command injection.
- End-to-end backend flow from webhook/manual trigger to fully persisted confidence report.

## Current Completion Estimate

Phase 1 backend foundation is roughly 93% complete for the deterministic core:
workspace, shared primitives, persistence schema, repository contracts, analysis
lifecycle, parser contracts, graph construction, git change extraction,
blast-radius computation, test discovery/selection, and confidence scoring are
implemented and validated. API exposure, worker orchestration, durable queue
state, durable artifact stores, subprocess test execution, tenant-scoped API
guards, idempotency replay, pull request upsert, and signed GitHub webhook
ingress now exist. Remaining work is concentrated in production worker context
resolution and full persisted webhook-to-confidence flow validation.

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
