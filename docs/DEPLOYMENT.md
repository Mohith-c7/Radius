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
| **`GEMINI_API_KEY`** | Google Gemini API key for the experimental Gemini call-site classifier. It is not part of the analysis pipeline and does not affect verdicts or test selection. | `AIzaSy...` |
| **`API_KEYS`** | Comma-separated API keys accepted by API in format `org_id:key`. | `00000000-0000-4000-8000-000000000001:radius_key_live` |
| **`GITHUB_APP_ID`** | GitHub App ID used to generate installation access tokens. | `123456` |
| **`GITHUB_APP_PRIVATE_KEY`** | RSA Private Key for the GitHub App (PEM format with `\n`). | `-----BEGIN RSA PRIVATE KEY-----\n...` |
| **`GITHUB_WEBHOOK_SECRET`** | Shared secret configured in the GitHub App webhook settings. | `whsec_live_secret_string` |
| **`GITHUB_DEFAULT_ORGANIZATION_ID`** | Default organization UUID assigned to webhook-created analyses. | `00000000-0000-4000-8000-000000000001` |
| **`GITHUB_PUBLISH_RESULTS`** | Whether the worker publishes Check Runs and PR comments to GitHub. | `true` |
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
   - **Webhook URL**: `https://api-radius.yourcompany.com/api/v1/github/webhooks`
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
