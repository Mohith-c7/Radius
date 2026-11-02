# Production Deployment Guide

This document covers the production runtime architecture, configuration, and deployment procedures for the Radius software verification platform.

---

## 1. Services Architecture

Radius runs as an orchestrated multi-service stack:

| Service | Technology | Port | Purpose |
| :--- | :--- | :--- | :--- |
| **`postgres`** | PostgreSQL 16 (Alpine) | `5432` | Relational storage for organizations, repositories, analyses, test runs, and confidence reports. |
| **`migrations`** | Alembic (one-shot container) | — | Automatically applies all pending database schema migrations on startup before the API launches. |
| **`api`** | FastAPI (Python 3.12, Uvicorn) | `8000` | REST API handling repository management, analysis triggers, predictive test queries, CI ingestion, and dashboard data. |
| **`worker`** | Python 3.12 Background Worker | — | Processes asynchronous analysis jobs, parses the repository, builds the dependency graph, slices diff hunks, selects tests, and publishes GitHub Check Runs. |
| **`dashboard`** | Next.js 15.5 (Node 22) | `3000` | Web console with interactive SVG CPG graph viewer, Predictive Test Selection Hub, CI report uploader, and real-time confidence metrics. |

---

## 2. Docker Compose Deployment

To spin up the entire production stack locally or on a single VM:

```bash
# Clone the repository
git clone https://github.com/Mohith-c7/Radius.git
cd Radius

# Configure production environment variables
cp .env.example .env.production
# (Edit .env.production with your database and GitHub App credentials)

# Build and start all services
docker compose --env-file .env.production up -d --build
```

### Healthcheck Verification

```bash
# Verify API service liveness and database readiness
curl -f http://localhost:8000/api/v1/health
curl -f http://localhost:8000/api/v1/ready

# Check logs
docker compose logs -f api worker dashboard
```

The Next.js web console is available at `http://localhost:3000`.

---

## 3. Production Environment Configuration

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| **`DATABASE_URL`** | PostgreSQL connection string for API, worker, and migrations. | `postgresql+psycopg://radius:password@postgres:5432/radius` |
| **`RADIUS_ENV`** | Application runtime environment (`production`, `development`). | `production` |
| **`RADIUS_LOG_LEVEL`** | Application logging level (`INFO`, `DEBUG`, `WARNING`). | `INFO` |
| **`RADIUS_FEATURE_SYMBOL_IMPACT`** | Worker: symbol-level test selection and blast radius for Python (F-08). Falls back to file-level impact when symbol info is missing or low-confidence. | `false` |
| **`RADIUS_FEATURE_SYMBOL_CHANGES`** | Worker: extract changed symbols (functions/methods/classes with change kinds) for the diff and log their counts (LK-01). Informational only; nothing is stored until LK-05 and failures never affect the analysis. | `false` |
| **`RADIUS_FEATURE_COVERAGE_CONTEXTS`** | Worker: allow the LK-03 dynamic coverage-context linker. It runs the selected tests under coverage.py with one context per test, only inside the hardened F-07 sandbox (no network, read-only root, limits, timeout); it refuses any other runner. The sandbox image must contain `pytest` and `coverage` (`FROM radius-sandbox-test` + `pip install coverage`). Not wired into the pipeline until LK-05. | `false` |
| **`GEMINI_API_KEY`** | Google Gemini API key for the experimental Gemini call-site classifier. It is not part of the analysis pipeline and does not affect verdicts or test selection. | `AIzaSy...` |
| **`RADIUS_LLM_INTENT_ENABLED`** | IN-04: master switch for LLM-assisted intent extraction. Off by default; the LLM only proposes criteria, never verdicts (DEC-009). Needs the `llm` extra. | `false` |
| **`RADIUS_LLM_INTENT_ORGS`** | Comma-separated organization ids that opted in (`*` = all). Egress is allowed only when the flag is on AND the org is listed. Only redacted intent text is sent, never repository code (DEC-015). | empty (none) |
| **`ANTHROPIC_API_KEY`** | Read from the environment by the Anthropic adapter, only when LLM intent extraction is enabled for the org. If it or the `anthropic` package is missing, the API logs a warning and skips the LLM extractor (fail closed); requests still succeed. | unset |
| **`RADIUS_LLM_INTENT_MODEL`** | Model id used by the Anthropic adapter. | `claude-haiku-5-5` |
| **`RADIUS_LLM_INTENT_ANALYSIS_TOKEN_CAP`** / **`RADIUS_LLM_INTENT_ORG_TOKEN_CAP`** | Token caps per analysis and per org (process lifetime); calls that would exceed them are skipped. | `30000` / `1000000` |
| **`RADIUS_LLM_INTENT_MAX_OUTPUT_TOKENS`**, **`_TIMEOUT_S`**, **`_MAX_ATTEMPTS`**, **`_BREAKER_THRESHOLD`**, **`_BREAKER_COOLDOWN_S`**, **`_MAX_CRITERIA`**, **`_SEED`** | Output cap, request timeout, bounded retries, circuit breaker and proposal cap (same `RADIUS_LLM_INTENT_` prefix). | `2048`, `30`, `3`, `5`, `60`, `20`, `0` |
| **`ANTHROPIC_API_KEY`** | API key for the Anthropic adapter (environment only; never logged). | `sk-ant-...` |
| **`API_KEYS`** | Comma-separated API keys accepted by API in format `org_id:key`. | `00000000-0000-4000-8000-000000000001:radius_key_live` |
| **`GITHUB_APP_ID`** | GitHub App ID used to generate installation access tokens. | `123456` |
| **`GITHUB_APP_PRIVATE_KEY`** | RSA Private Key for the GitHub App (PEM format with `\n`). | `-----BEGIN RSA PRIVATE KEY-----\n...` |
| **`GITHUB_WEBHOOK_SECRET`** | Shared secret configured in the GitHub App webhook settings. | `whsec_live_secret_string` |
| **`GITHUB_DEFAULT_ORGANIZATION_ID`** | Default organization UUID assigned to webhook-created analyses. | `00000000-0000-4000-8000-000000000001` |
| **`GITHUB_SINGLE_TENANT`** | `true` routes deliveries from installations not yet linked to an organization to `GITHUB_DEFAULT_ORGANIZATION_ID`. Safe only when one organization uses the App; default `false` rejects them (403). | `false` |
| **`GITHUB_PUBLISH_RESULTS`** | Whether the worker publishes Check Runs and PR comments to GitHub. | `true` |
| **`RADIUS_TRACING_ENABLED`** | Enable OpenTelemetry tracing (needs the `observability` extra). Off by default. See `docs/OBSERVABILITY.md`. | `false` |
| **`RADIUS_OTLP_ENDPOINT`** | OTLP/HTTP traces endpoint; empty records spans without exporting. | `http://jaeger:4318/v1/traces` |
| **`RADIUS_METRICS_ENABLED`** | Expose Prometheus metrics at `/metrics` (API) and on the worker metrics port. Off by default. | `false` |
| **`RADIUS_WORKER_METRICS_PORT`** | Worker Prometheus port; `0` disables it. | `9100` |
| **`DASHBOARD_BASE_URL`** | Canonical public URL of the dashboard used in PR comment links. | `https://radius.yourcompany.com` |
| **`NEXT_PUBLIC_RADIUS_API_BASE_URL`** | Public URL used by the browser to communicate with the API. | `https://api-radius.yourcompany.com` |
| **`NEXT_PUBLIC_RADIUS_ORGANIZATION_ID`** | Tenant organization UUID loaded by the dashboard. | `00000000-0000-4000-8000-000000000001` |
| **`RADIUS_API_KEY`** | Server-only secret the dashboard proxy (`/api/radius/*`) attaches as `X-Radius-API-Key`. Never use a `NEXT_PUBLIC_` prefix; leave empty only with `RADIUS_ALLOW_INSECURE_DEV`. | *(empty; set a secret)* |

---

> **Demo data:** `RADIUS_SEED_DEMO_DATA=true` seeds hand-written Bottle/Emittery demo fixtures (labelled "DEMO FIXTURE", not real analyses) and a `demo@radius.dev` login with a publicly known password. It defaults to `false` and is always ignored when `RADIUS_ENV=production`.

## 4. GitHub App Setup & Permissions

To configure Radius to automatically verify Pull Requests:

1. Create a GitHub App under your GitHub Organization:
   - **Homepage URL**: `https://radius.yourcompany.com`
   - **Webhook URL**: `https://api-radius.yourcompany.com/api/v1/webhooks/github` (content type `application/json`)
   - **Webhook Secret**: Generate a secure 32+ character string and set as `GITHUB_WEBHOOK_SECRET`.
2. Configure Permissions:
   - **Repository contents**: Read (to clone and parse repository ASTs)
   - **Pull requests**: Read & Write (to inspect PR diffs and post verification markdown comments)
   - **Checks**: Read & Write (to publish `Radius confidence` in-progress and completed Check Runs)
   - **Metadata**: Read
3. Subscribe to Webhook Events:
   - `pull_request` (opened, synchronize, reopened)
   - `push`
4. Generate a Private Key, download the `.pem` file, and assign the content to `GITHUB_APP_PRIVATE_KEY`.
5. Install the App onto your organization's repositories.

---

## 5. Security & Isolation

- **Tenant Isolation**: Every API request requires an `X-Radius-Organization-Id` header (and optional Bearer API key). Data queries strictly scope records by organization ID.
- **Symlink Traversal Defense**: The worker uses `os.path.realpath` bounds checking during repository filesystem traversal to prevent symlink escape vulnerabilities.
- **No LLM on the verdict path**: the experimental semantic pruner is not invoked by the worker pipeline, so no model output can remove tests or dependency edges from the selection (see `docs/audit/RADIUS_AUDIT.md`).
- **No Unsafe Code Execution**: Worker analysis is static parsing and graph traversal; untrusted repository code is never executed inside worker containers.
