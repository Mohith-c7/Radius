# Decisions

This file records project-level decisions that should guide implementation.

## DEC-001: Radius is the canonical product name

Radius replaces the earlier ShipSafe naming in README and developer-facing documentation. Future code, folders, APIs, UI copy, and docs should use Radius.

## DEC-002: Uppercase docs are the source of truth

The substantive documents such as `PROJECT_OVERVIEW.md`, `PHASE1_SPECIFICATION.md`, `MODULE_ARCHITECTURE.md`, `DATABASE_DESIGN.md`, and `API_CONTRACTS.md` are canonical. Lowercase legacy files remain only as compatibility pointers.

## DEC-003: Phase 1 package scaffold follows domain boundaries

The Phase 1 package layout is:

- `repository`
- `parser`
- `graph`
- `analysis`
- `testing`
- `confidence`
- `shared`

Earlier placeholder packages that represented future or implementation-specific concerns are removed until a documented phase requires them.

## DEC-004: Phase 1 pipeline order

The Phase 1 execution pipeline is:

1. Receive GitHub event or manual analysis trigger.
2. Synchronize the repository.
3. Analyze the Git diff to identify changed files.
4. Parse source files and extract semantic metadata.
5. Build or update the dependency graph.
6. Compute changed symbols and blast radius.
7. Select and execute relevant existing tests.
8. Generate an explainable confidence report.
9. Publish results through the API, dashboard, and GitHub Check.

The diff step may run before parsing to limit work, but deterministic parsing and graph data remain the foundation for impact analysis.

## DEC-005: Branching model

Radius uses an enterprise promotion flow:

```text
feature/* -> develop -> dev -> main
```

- `feature/*` branches are short-lived branches for isolated implementation work.
- `develop` is the active development integration branch.
- `dev` is the UAT branch. Feature branches must not merge directly into `dev`.
- `main` is the release branch and contains only release-ready code.
- `release/*` branches are optional and used only for named release stabilization.
- `hotfix/*` branches start from `main`, then merge back into `main`, `dev`, and `develop`.

This gives Radius a controlled promotion path while keeping feature work isolated before UAT.
