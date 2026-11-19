# 07_Folder_Structure.md

# Folder Structure

Project: Radius

Version: 1.0

---

# Overview

Radius follows a modular monorepo architecture.

The repository is organized around business domains rather than technical layers.

Every domain owns its own business logic, infrastructure, interfaces, and tests.

This structure allows independent development, easier maintenance, and seamless future scaling.

---

# Repository Structure

```text
radius/

├── apps/
│
├── packages/
│
├── docs/
│
├── infra/
│
├── scripts/
│
├── .github/
│
├── package.json
├── pnpm-workspace.yaml
├── turbo.json
└── README.md
```

---

# apps/

Contains executable applications.

```text
apps/

├── dashboard/
├── api/
└── worker/
```

---

## dashboard/

Next.js application.

Responsibilities

- User Interface
- Authentication
- Repository Management
- Analysis Dashboard
- Dependency Visualization
- Confidence Reports

Never contains business logic.

---

## api/

FastAPI application.

Responsibilities

- REST APIs
- Authentication
- Request Validation
- Domain Coordination
- Event Dispatching

Business logic belongs inside packages.

---

## worker/

Background processing.

Responsibilities

- Long-running analysis
- Graph rebuilding
- Test execution
- Report generation

Phase 1 may execute synchronously.

Future versions may move work into queues. (As implemented: the worker consumes a durable SQL job queue, `analysis_jobs`, with leases and backoff.)

---

# packages/

Contains all business domains.

```text
packages/

repository/
parser/
graph/
analysis/
testing/
confidence/
intent/        # research: intent layer (DEC-007)
evidence/      # research: evidence quality, support and UIM for Verdict v2 (DEC-027)
linking/       # criterion-to-symbol and criterion-to-test links (DEC-026)
github/        # GitHub App client, PR comment and Check Run publishing
shared/
```

---

# Domain Structure

Every domain follows exactly the same layout.

```text
domain/

application/

domain/

infrastructure/

interfaces/

dto/

tests/

README.md
```

---

## application/

Coordinates business use cases.

Contains

- Services
- Use Cases
- Commands
- Queries

No infrastructure code.

---

## domain/

Pure business rules.

Contains

- Entities
- Value Objects
- Interfaces
- Domain Services

Must never depend on frameworks.

---

## infrastructure/

Technical implementations.

Contains

- Database
- GitHub
- Tree-sitter
- git CLI (subprocess; GitPython is not used)
- File System

May depend on external libraries.

---

## interfaces/

External communication.

Contains

- REST Controllers
- API Models
- Event Handlers

Coordinates requests.

Never contains business logic.

---

## dto/

Request and response models.

Contains

- Request DTOs
- Response DTOs
- Mappers

---

## tests/

Domain-specific tests.

Contains

- Unit Tests
- Integration Tests

---

# Repository Domain

```text
repository/

application/

domain/

infrastructure/

interfaces/

dto/

tests/
```

Responsible for

- GitHub
- Git
- Repository Cache
- Repository Metadata

---

# Parser Domain

Responsible for semantic extraction.

Infrastructure

- Tree-sitter

Domain

- AST
- Symbols
- Imports
- Exports

---

# Graph Domain

Infrastructure

- In-house adjacency structures (NetworkX is not a dependency)

Responsibilities

- Graph Construction
- Traversal
- Dependency Resolution

---

# Analysis Domain

Responsibilities

- Git Diff
- Blast Radius
- Impact Analysis
- Risk Analysis

---

# Testing Domain

Responsibilities

- Test Discovery
- Test Selection
- Test Execution
- Coverage

---

# Confidence Domain

Responsibilities

- Confidence Score
- Evidence Collection
- Report Generation

---

# Shared Package

Contains reusable components.

```text
shared/

config/

logging/

events/

database/

auth/

cache/

errors/

types/

utils/

constants/
```

Only reusable code belongs here.

---

# docs/

Project documentation.

```text
docs/

AI_CONTEXT.md
API_CONTRACTS.md
DATABASE_DESIGN.md
DEVELOPMENT_GUIDE.md
DOMAIN_MODEL.md
FOLDER_STRUCTURE.md
MODULE_ARCHITECTURE.md
PHASE1_SPECIFICATION.md
PRODUCT_VISION.md
PROJECT_OVERVIEW.md
SYSTEM_ARCHITECTURE.md
USE_CASES.md
decisions.md
roadmap.md
```

`AI_CONTEXT.md` is the required entry point for AI coding assistants.

---

# infra/

Infrastructure configuration.

```text
infra/

docker/

nginx/

compose/

terraform/

kubernetes/
```

Only Docker is needed during Phase 1. As implemented, `infra/` holds `database/migrations` (Alembic) and `observability/`; the Dockerfiles live under `apps/*/` and the Compose files at the repository root.

---

# scripts/

Automation scripts.

Examples

Repository setup

Development

Formatting

Code generation

Database

---

# .github/

GitHub automation.

Contains

```text
.github/

workflows/

ISSUE_TEMPLATE/

pull_request_template.md
```

---

# Architectural Rules

Every domain owns its code.

Domains never import infrastructure from another domain.

Business rules never depend on frameworks.

Controllers never contain business logic.

Repositories never know about HTTP.

Entities never know about databases.

---

# Naming Conventions

Folders

lowercase

Packages

singular nouns

Classes

PascalCase

Functions

snake_case in Python (ruff); camelCase in TypeScript

Constants

UPPER_SNAKE_CASE

Files

snake_case for Python

Documentation: mostly UPPER_SNAKE_CASE (`DATABASE_DESIGN.md`), with some kebab-case (`verdict-v2.md`)

---

# Dependency Rules

Allowed

Application → Domain

Infrastructure → Domain

Interfaces → Application

Not Allowed

Domain → Infrastructure

Domain → Framework

Application → Database

Presentation → Parser

Presentation → Graph

---

# Future Expansion

The structure supports future domains including

Security

AI

Knowledge

Plugins

Notifications

MCP

CLI

VS Code Extension

without restructuring the repository.

---

# Summary

The Radius repository is organized around business capabilities rather than technical layers.

Every domain is independently maintainable, testable, and extensible.

This architecture allows Radius to evolve into a large-scale engineering platform while maintaining clear ownership boundaries.
