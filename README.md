# Radius

> The AI-native confidence layer for modern software development.

Radius is an AI-native software verification platform that helps engineering teams understand whether a pull request is safe to merge.

Radius does not replace existing test frameworks, CI/CD systems, or code editors. It sits between code changes and production deployment, analyzes the repository as an interconnected system, and produces explainable verification evidence before merge.

---

## The Core Question

Every subsystem in Radius contributes to one fundamental question:

```text
Can this Pull Request be merged safely?
```

---

## Key Capabilities

1. **Multi-Language Code Property Graph (CPG)**:
   - **Python** is parsed with the standard-library `ast` module; **TypeScript / JavaScript** imports and symbols are extracted with a lightweight regex parser (no tree-sitter, no tsconfig path aliases or package exports). Go, Java and Rust have tree-sitter parsers, but their imports are not yet resolved to files.
   - Resolves cross-file symbol references and import statements into a directed dependency graph.
2. **Diff-Hunk Line Precision**:
   - Parses unified git diff hunks to identify exact modified line numbers.
   - Slices only symbols directly affected by modified lines, skipping untouched sibling functions in edited files.
3. **Gemini Semantic Analysis (experimental, advisory only)**:
   - A proof-of-concept LLM call-site classifier exists, but it is **not** on the verdict path: no model output can remove tests or dependency edges from the selection (see `docs/audit/RADIUS_AUDIT.md`, P0-8).
4. **Dependency-Graph Test Selection**:
   - Selects test files that reach a changed file through the file-level import graph, plus naming-convention matches (`pytest`, `vitest`, `jest`).
   - Executes only the tests the dependency graph reaches from the change (with a full-suite fallback when the graph cannot map it). No general time-saving figure is claimed; measured selection/time numbers on a small self-evaluation corpus are in [docs/benchmarks/REAL_REPO_BENCHMARK.md](docs/benchmarks/REAL_REPO_BENCHMARK.md).
   - Generates multi-framework CLI strings directly executable in local or CI runners.
5. **Universal CI Ingestion & Dynamic Confidence Engine**:
   - Ingests standard **JUnit XML** and **JSON** test execution reports from any CI runner.
   - Uploads are bound to the analysed head commit and must cover the selected tests; the evidence-gated verdict (`verified` / `failed` / `insufficient_evidence`) is recomputed from all uploads. The 0-100 score is an uncalibrated heuristic, not a calibrated probability; the API labels it with `score_kind="heuristic_uncalibrated"` and the PR comment, Check Run and dashboard repeat the label.
6. **Rich GitHub App Integration**:
   - Publishes `Radius confidence` Check Runs with `in_progress` status on webhook arrival and `completed` status upon verification.
   - Formats GitHub PR comments with the verdict, the reasons a change is not verified, and collapsible blast radius tables. The Check Run is published when the analysis completes; it is not yet re-published after CI uploads (the CI job's exit code is the merge gate for uploaded evidence).
7. **Interactive Next.js Dashboard**:
   - Interactive SVG Graph Visualizer with layered DAG layout, pan/zoom, filter pills, and symbol inspector drawer.
   - Test Selection Hub with 1-click CLI runner command copy.
   - Ingestion modal for pasting or uploading JUnit XML and JSON test reports with live confidence refreshes.

---

## Monorepo Architecture

```text
radius/
├── apps/
│   ├── api/            FastAPI REST API (Python 3.12, Uvicorn)
│   ├── dashboard/      Next.js 15.5 React/TypeScript Web Console
│   └── worker/         Durable Analysis Worker (parsing, CPG, test selection; polls the PostgreSQL job queue)
│
├── packages/
│   ├── analysis/       Diff hunk parser, change detection, SQL job queue, experimental AI semantic pruner (not on the verdict path)
│   ├── confidence/     Deterministic & dynamic confidence scoring engine
│   ├── github/         GitHub App client, Check Runs & PR publisher
│   ├── graph/          Code Property Graph (CPG), graph slicer, module resolver
│   ├── parser/         Python `ast` parser, JS/TS regex parser, tree-sitter Go/Java/Rust parsers and POC extractors
│   ├── repository/     Git repository clones, branch tracking, and snapshots
│   ├── shared/         Database models, auth tokens, configuration, events
│   └── testing/        Graph-driven test selector, JUnit XML parser, planners
│
├── docs/               Deployment, CI integration, architecture, and API docs
├── infra/              Alembic database migrations and docker configurations
└── tests/              End-to-end multi-language target verification test suite
```

---

## Quickstart: Docker Compose

Spin up the entire Radius production stack with PostgreSQL, API, Worker, and Next.js Dashboard (the job queue is a table in PostgreSQL; there is no Redis):

```bash
# Clone the repository
git clone https://github.com/Mohith-c7/Radius.git
cd Radius

# Configure environment
cp .env.example .env.production

# Run all services
docker compose --env-file .env.production up -d --build
```

- **Next.js Dashboard**: `http://localhost:3000`
- **FastAPI API**: `http://localhost:8000/api/v1/health`
- **API Documentation**: `http://localhost:8000/docs`

---

## Local Development & Testing

```bash
# Install Python dependencies and run the Python test suite
python -m pytest

# Install frontend dependencies and run dashboard tests
pnpm --filter dashboard run test

# Typecheck and compile production Next.js build
pnpm --filter dashboard run build
```

---

## Documentation

- **[Production Deployment Guide](docs/DEPLOYMENT.md)**: Full production runtime configuration, Docker orchestration, and security.
- **[CI/CD Integration Guide](docs/CI_INTEGRATION_GUIDE.md)**: Integrating predictive test selection into GitHub Actions and uploading JUnit XML reports.
- **[System Architecture](docs/SYSTEM_ARCHITECTURE.md)**: In-depth technical architecture and data flow.
