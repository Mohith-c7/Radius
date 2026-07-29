# Radius

> The confidence layer for modern software development.

Radius is an AI-native software verification platform that helps engineering teams understand whether a pull request is safe to merge.

Radius does not replace existing test frameworks, CI/CD systems, source hosts, or code editors. It sits between code changes and production deployment, analyzes the repository as an interconnected system, and produces explainable verification evidence before merge.

## Core Question

Every subsystem in Radius contributes to one question:

```text
Can this Pull Request be merged safely?
```

## Product Direction

Phase 1 is deterministic first. Radius must understand repositories before AI is allowed to influence engineering decisions.

The Phase 1 workflow is:

```text
GitHub event or manual trigger
Repository synchronization
Git diff and changed-file detection
Parser and symbol extraction
Dependency graph update
Blast radius computation
Relevant test selection and execution
Explainable confidence report
Dashboard and GitHub Check output
```

AI-assisted capabilities such as test generation, risk summarization, security intelligence, and historical learning are future enhancements. They should integrate through stable contracts after the deterministic foundation is reliable.

## Target Users

- Software engineers reviewing pull requests
- Technical leads assessing merge risk
- DevOps and platform teams improving release confidence
- Organization admins managing GitHub integrations and repositories
- Teams adopting AI-assisted software development

## Phase 1 Scope

Radius Phase 1 focuses on:

- GitHub App integration
- Repository synchronization
- Source parsing with Tree-sitter
- Symbol, import, and export extraction
- Dependency graph generation with NetworkX
- Git change analysis
- Blast radius computation
- Relevant existing test execution
- Explainable confidence scoring
- FastAPI REST API
- Next.js dashboard

## Repository Structure

```text
radius/
apps/
  api/          FastAPI application
  dashboard/    Next.js dashboard
  worker/       Background analysis worker

packages/
  repository/   GitHub, Git, repository snapshots
  parser/       Source parsing and semantic extraction
  graph/        Dependency graph construction and traversal
  analysis/     Git diff, changed symbols, blast radius
  testing/      Test discovery, selection, execution, coverage
  confidence/   Evidence aggregation and confidence reports
  shared/       Config, logging, events, auth, errors, shared types

docs/           Product, architecture, API, database, and workflow docs
infra/          Infrastructure configuration
scripts/        Development and automation scripts
.github/        GitHub workflows and templates
```

## Technology Stack

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui
- Backend: FastAPI, Python 3.12+, Pydantic, SQLAlchemy, Alembic
- Database: PostgreSQL
- Parsing: Tree-sitter
- Graph: NetworkX
- Git: GitPython
- Authentication: GitHub OAuth and GitHub App
- Tooling: pnpm, TurboRepo, Docker, Ruff, Black, Pytest, ESLint, Prettier

## Documentation

The primary docs are in `docs/`.

- `PROJECT_OVERVIEW.md`
- `PRODUCT_VISION.md`
- `PHASE1_SPECIFICATION.md`
- `SYSTEM_ARCHITECTURE.md`
- `MODULE_ARCHITECTURE.md`
- `DOMAIN_MODEL.md`
- `FOLDER_STRUCTURE.md`
- `DATABASE_DESIGN.md`
- `API_CONTRACTS.md`
- `USE_CASES.md`
- `DEVELOPMENT_GUIDE.md`
- `roadmap.md`
- `AI_CONTEXT.md`
- `decisions.md`

`AI_CONTEXT.md` is required reading before any implementation work.

## Branch Strategy

Development follows trunk-based branching:

- `main` is the protected integration and release branch.
- Feature work uses short-lived branches named `codex/feature/<area>-<summary>`.
- Fixes use `codex/fix/<area>-<summary>`.
- Documentation-only changes use `codex/docs/<summary>`.
- Release stabilization, when needed, uses `release/<version>`.
- Hotfixes use `hotfix/<summary>` and merge back to `main`.

Pull requests should be small, reviewable, and aligned to one domain or workflow whenever possible.

## Development Status

Radius is at the foundation stage. The repository currently contains the monorepo scaffold and product/architecture documentation. Implementation should proceed from the documented Phase 1 contracts and domain boundaries.

## License

This project is currently proprietary.
