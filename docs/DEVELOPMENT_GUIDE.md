# 09_Development_Guide.md

# Development Guide

**Project:** Radius

**Version:** 1.0

---

# Purpose

This document defines the engineering workflow for developing Radius.

It establishes the project structure, coding workflow, branching strategy, quality standards, and development practices to ensure consistency across contributors.

---

# Quickstart

Goal: from a fresh clone to a running dashboard, API and worker in under 15 minutes. The first `make dev` is dominated by the Docker image build (about 10 minutes on a cold cache in the reference run; later starts take under a minute).

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker (Desktop on Windows/macOS) with Compose v2 | tested with Docker 29.7 / Compose 5.3 | the one-command stack |
| [uv](https://docs.astral.sh/uv/) | tested with 0.12 | Python 3.12 environment and tests |
| Node.js | CI uses 22; tested with 24 | dashboard and the pnpm/turbo workspace |
| pnpm | 9.15.0 (pinned in `package.json`) | via `corepack`, see Windows notes |
| GNU make | optional | `make` targets; Windows users can use `scripts/dev.ps1` instead |

## One command

```bash
git clone https://github.com/Mohith-c7/Radius.git && cd Radius
make dev            # Linux, macOS, WSL, Git Bash
```

```powershell
.\scripts\dev.ps1 dev     # Windows PowerShell, no make required
```

`dev` copies `.env.example` to `.env` if missing (it never overwrites) and adds a local-dev `GITHUB_DEFAULT_ORGANIZATION_ID` (Compose would otherwise pass an empty value, which the API rejects as an invalid UUID), builds the images and starts Postgres, the migrations job, the API, the worker and the dashboard, waiting until they are healthy.

| What | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |

Stop with `make down` (or `.\scripts\dev.ps1 down`). `pnpm dev:stack`, `pnpm dev:down` and `pnpm dev:logs` do the same through pnpm. Every target is listed by `make help` or `.\scripts\dev.ps1 help`.

## Develop with hot reload (no Docker for the app)

```bash
make setup          # uv sync --frozen --extra dev, corepack enable, pnpm install
make dev-local      # API + worker + dashboard natively, in-memory storage
make test           # python -m pytest
make lint           # ruff
```

`dev-local` runs `pnpm dev` (turbo) with the project `.venv` first on `PATH`, so the Python services use it. The in-memory backend needs no database. Run `make setup` first.

## Compose profiles

| Profile | Services | Notes |
|---|---|---|
| core (default) | `postgres`, `migrations`, `api`, `worker`, `dashboard` | Carries no `profiles:` key so the documented `docker compose up -d --build` still works. |
| `sandbox` | `sandbox-image` | One-shot build of the image used when `WORKER_TEST_EXECUTION_MODE=sandbox`. The worker starts per-command containers itself and needs a container runtime, so run the worker natively (`make dev-local`) for sandbox mode. See `docs/security/EXECUTION_ISOLATION.md`. |
| `observability` | `jaeger`, `prometheus` | Local tracing and metrics backends. Build api/worker with `RADIUS_EXTRAS=[observability]` to emit data. See `docs/OBSERVABILITY.md`. |

```bash
make sandbox          # docker compose --profile sandbox up --build sandbox-image
make observability    # docker compose --profile observability up jaeger prometheus
```

## Demo data (opt-in)

Nothing is seeded by default. Demo data is illustrative: hand-written fixtures for two open-source targets plus a demo login (`demo@radius.dev`) with a publicly documented password. It is **not real analysis output**, is ignored when `RADIUS_ENV=production`, and must only be used on disposable local databases.

```bash
make dev-local-demo   # in-memory API, seeded at start-up
make seed-demo        # into the Docker Postgres from `make dev` (STORAGE_BACKEND=sql)
```

`make seed-demo` runs `scripts/seed_demo.py --yes`, which prints a "DEMO DATA" banner and refuses to run without `--yes` or with `RADIUS_ENV=production`. Note that the Compose API runs with `RADIUS_ENV=production`, so it never seeds itself; the script writes into the same Postgres database from your host.

## Windows notes

- **pnpm via corepack.** `package.json` pins `pnpm@9.15.0`. Run `corepack enable` once. If Node is installed under `C:\Program Files` this fails with `EPERM: operation not permitted, open 'C:\Program Files\nodejs\pnpm'` unless the shell is elevated. Without administrator rights run `corepack enable --install-directory "$env:USERPROFILE\bin"` and put that directory first on `PATH`; `pnpm -v` then prints `9.15.0`. Use PowerShell or cmd for pnpm: the shims are `.cmd`/`.ps1` files that Git Bash does not find by the bare name `pnpm`.
- **No make.** Use `.\scripts\dev.ps1 <target>`; targets match the Makefile. If script execution is blocked: `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 dev`. Alternatively `winget install ezwinports.make`, or work inside WSL.
- **Docker Desktop** must be running (`docker info` succeeds). Use the WSL 2 backend and keep the clone on a path without spaces.
- **Hot-reload on Linux/macOS.** The per-app `dev` scripts build `PYTHONPATH` with `;`, which is the Windows separator, so `make dev-local` has only been exercised on Windows. On Linux/macOS prefer `make dev` (Docker).
- **`uv`**: install with `winget install astral-sh.uv`.

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

Radius uses an enterprise promotion flow.

```text
feature/* | fix/* | docs/*  ->  develop  ->  dev (UAT)  ->  main
```

The GitHub default branch is `develop`, so new pull requests target it unless you pick another base.

Nobody commits directly to `develop`, `dev` or `main`; every change arrives through a pull request that passes the required status checks. Never push test or throwaway commits to `dev` or `main`. Settings and rationale are in `docs/github-branch-protection.md`; the decision is DEC-005 (flow) and DEC-010 (default branch) in `docs/decisions.md`.

## Main

`main` is the release branch.

Only release-ready code should reach `main`, promoted from `dev` by an owner.

---

## UAT

`dev` is the UAT branch.

Only work promoted from `develop` should merge into `dev`.

Feature branches must not merge directly into `dev`.

---

## Develop

`develop` is the active development integration branch.

Feature branches merge into `develop` after review and automated checks.

`develop` may contain work that is ready for internal integration but not yet ready for UAT.

---

## Feature Branches

Feature branches use the `feature/` prefix.

Naming convention:

```text
feature/<area>-<summary>

Examples

feature/repository-github-app

feature/parser-symbol-extraction

feature/analysis-blast-radius
```

---

## Bug Fixes

Bug fixes use the `fix/` prefix and normally merge into `develop`.

```text
fix/<area>-<summary>
```

---

## Documentation

Documentation-only work uses the `docs/` prefix and normally merges into `develop`.

```text
docs/<summary>
```

---

## Releases

Release stabilization branches are optional and created only for named release preparation.

```text
release/<version>
```

Release branches may be created from `dev` when UAT is complete but final release stabilization is needed before `main`.

---

## Hotfixes

Urgent production fixes use:

```text
hotfix/<summary>
```

Promotion (`develop` -> `dev` -> `main`) uses pull requests and merge commits, so the same commits flow forward and the branches stay comparable.

Every Pull Request must (the PR template at `.github/pull_request_template.md` carries this checklist):

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

# Troubleshooting


| Symptom | Fix |
|---|---|
| `port is already allocated` on 5432 | Another Postgres uses it. Set `POSTGRES_HOST_PORT=5433` (any free port) in `.env`. Ports 3000 and 8000 are fixed (CORS and the dashboard build assume them): stop whatever else uses them. |
| `make: command not found` | Use `.\scripts\dev.ps1` (Windows) or install make. |
| `docker compose up --wait` times out | `make logs` and `docker compose ps -a`. The `migrations` job must exit 0 before the API starts; a failing migration shows in `docker compose logs migrations`. |
| API unhealthy right after start | It waits for Postgres and migrations; give it up to a minute on a cold start. `curl http://localhost:8000/api/v1/ready`. |
| `The lockfile at uv.lock needs to be updated` / `uv sync` rewrites `uv.lock` | Use the `--frozen` forms shown here. Commit lock changes only in a dedicated dependency PR. |
| `pnpm: command not found` | `corepack enable` (see Windows notes). |
| `Access is denied` while `uv sync` replaces `.venv` files (Windows) | A Python process (pytest, uvicorn, an IDE) still has the venv loaded. Stop it and rerun. |
| Dashboard cannot reach the API | `NEXT_PUBLIC_RADIUS_API_BASE_URL` is baked in at build time. Edit `.env`, then `make dev` (it rebuilds). |
| Fresh start / reset the database | `make clean-volumes` (destructive: deletes the Postgres volume). |
| `test_secure_defaults.py::test_missing_secrets_are_rejected[development-None]` fails | The test removes `RADIUS_ALLOW_INSECURE_DEV` from the process environment, but settings still read it from `.env` (copied from `.env.example`, which sets it to `true`). Run the suite with `.env` moved aside. |
| Other test failures on Windows | Seen on a Windows 11 run of `develop`: `test_sandbox_runner.py` (POSIX path assumptions, symlink privilege `WinError 1314`) and `test_subprocess_runner.py::test_subprocess_runner_executes_pytest_plan`. `benchmarks/test_benchmarks.py::test_confidence_scoring_completeness_and_verification_status` failed when run alone but passed in the full run. Treat these as known issues, not setup problems. |

---

# Summary

Radius is developed through small, incremental, production-quality changes. Every contribution should improve the platform while preserving modularity, maintainability, and long-term scalability.
