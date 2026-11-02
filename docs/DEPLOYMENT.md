# Production Deployment Guide

This document covers the production runtime architecture, configuration, and deployment procedures for the Radius software verification platform. Step-by-step install, upgrade, backup, hardening and runbook pages are in [operations/](operations/README.md); the complete, generated environment variable reference is [operations/CONFIGURATION.md](operations/CONFIGURATION.md). The table in section 3 is a curated subset.

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
# (Edit .env.production with your database and GitHub App credentials.
#  .env.example is a development template: remove RADIUS_ALLOW_INSECURE_DEV, set real
#  API_KEYS, RADIUS_API_KEY, GITHUB_WEBHOOK_SECRET and SESSION_SECRET. See operations/INSTALL.md.)

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

### Container runtime behavior (PRD-08)

All three images run as the non-root user `radius` (uid/gid `10001:10001`) and define a
`HEALTHCHECK` (api: `/api/v1/ready`; worker: database reachability; dashboard: `GET /login`).
Check them with `docker compose ps` (the STATUS column shows `healthy`) or
`docker inspect --format '{{.State.Health.Status}}' <container>`.

* Named volumes that existed before this change were created root-owned. For the worker's
  repository cache, either recreate the volume (`docker compose down -v` drops it, and the
  cache is rebuildable) or `chown -R 10001:10001` its contents once.
* Read-only root filesystems are supported (verified with `--read-only --cap-drop ALL`).
  The api and dashboard need no writable path; the worker needs its repository cache volume
  (`/var/lib/radius/repositories`) and, as a precaution, a tmpfs on `/tmp`. Exact commands are in
  [security/CONTAINERS.md](security/CONTAINERS.md).
* Worker sandbox mode (`WORKER_TEST_EXECUTION_MODE=sandbox`) needs a container runtime. The
  default worker image has none; build the `sandbox` target (adds the docker CLI) and give
  it a daemon, see [security/CONTAINERS.md](security/CONTAINERS.md) and
  [security/EXECUTION_ISOLATION.md](security/EXECUTION_ISOLATION.md).

---

## 3. Production Environment Configuration

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| **`DATABASE_URL`** | PostgreSQL connection string for API, worker, and migrations. | `postgresql+psycopg://radius:password@postgres:5432/radius` |
| **`RADIUS_ENV`** | Application runtime environment: `development`, `test`, `uat` or `production`. Compose forces `production` for api and worker. | `production` |
| **`RADIUS_LOG_LEVEL`** | Application logging level (`INFO`, `DEBUG`, `WARNING`). | `INFO` |
| **`RADIUS_FEATURE_SYMBOL_IMPACT`** | Worker: symbol-level test selection and blast radius for Python (F-08). Falls back to file-level impact when symbol info is missing or low-confidence. | `false` |
| **`RADIUS_FEATURE_SYMBOL_CHANGES`** | Worker: extract changed symbols (functions/methods/classes with change kinds) for the diff and log their counts (LK-01). Informational only; nothing is stored until LK-05 and failures never affect the analysis. | `false` |
| **`RADIUS_FEATURE_COVERAGE_CONTEXTS`** | Worker: allow the LK-03 dynamic coverage-context linker. It runs the selected tests under coverage.py with one context per test, only inside the hardened F-07 sandbox (no network, read-only root, limits, timeout); it refuses any other runner. The sandbox image must contain `pytest` and `coverage` (`FROM radius-sandbox-test` + `pip install coverage`). Not wired into the pipeline until LK-05. | `false` |
| **`GEMINI_API_KEY`** | Credential for the **legacy** Gemini `SemanticPruner`. Leave unset. It is used only when `RADIUS_FEATURE_GEMINI_PRUNER=true` is also set and is not called by the analysis pipeline (only by tests and `scripts/run_phase2_poc.py`). When active it sends caller source code and diffs to Google Gemini, a third party, and it is **not** covered by the LLM egress policy of DEC-021. It never affects verdicts or test selection. | unset |
| **`RADIUS_FEATURE_GEMINI_PRUNER`** | Explicit opt-in for the legacy Gemini pruner (before this flag existed, the key alone enabled it). See `GEMINI_API_KEY` above and [security/PROMPT_INJECTION.md](security/PROMPT_INJECTION.md) for the egress rules. | `false` |
| **`RADIUS_FEATURE_TAMPER_RULES`** | Worker: run the EV-02 deterministic tamper rules on the diff and log finding counts. Nothing is stored by this step; the Verdict v2 alpha runs the rules itself. Failures never affect the analysis. | `false` |
| **`RADIUS_FEATURE_ASSERTION_EXTRACTION`** | Worker: statically extract test assertions (LK-04, AST only, nothing executed) and log counts. Failures never affect the analysis. | `false` |
| **`RADIUS_LLM_INTENT_ENABLED`** | IN-04: master switch for LLM-assisted intent extraction. Off by default; the LLM only proposes criteria, never verdicts (DEC-009). Needs the `llm` extra. | `false` |
| **`RADIUS_LLM_INTENT_ORGS`** | Comma-separated organization ids that opted in (`*` = all). Egress is allowed only when the flag is on AND the org is listed. Only redacted intent text is sent, never repository code (DEC-015). | empty (none) |
| **`ANTHROPIC_API_KEY`** | Read from the environment by the Anthropic adapter, only when LLM intent extraction is enabled for the org. If it or the `anthropic` package is missing, the API logs a warning and skips the LLM extractor (fail closed); requests still succeed. | unset |
| **`RADIUS_LLM_INTENT_MODEL`** | Model id used by the Anthropic adapter. | `claude-haiku-5-5` |
| **`RADIUS_LLM_INTENT_ANALYSIS_TOKEN_CAP`** / **`RADIUS_LLM_INTENT_ORG_TOKEN_CAP`** | Token caps per analysis and per org (process lifetime); calls that would exceed them are skipped. | `30000` / `1000000` |
| **`RADIUS_LLM_INTENT_MAX_OUTPUT_TOKENS`**, **`_TIMEOUT_S`**, **`_MAX_ATTEMPTS`**, **`_BREAKER_THRESHOLD`**, **`_BREAKER_COOLDOWN_S`**, **`_MAX_CRITERIA`**, **`_SEED`** | Output cap, request timeout, bounded retries, circuit breaker and proposal cap (same `RADIUS_LLM_INTENT_` prefix). | `2048`, `30`, `3`, `5`, `60`, `20`, `0` |
| **`API_KEYS`** | Comma-separated API keys accepted by API in format `org_id:key`. | `00000000-0000-4000-8000-000000000001:radius_key_live` |
| **`GITHUB_APP_ID`** | GitHub App ID used to generate installation access tokens. | `123456` |
| **`GITHUB_APP_PRIVATE_KEY`** | RSA Private Key for the GitHub App (PEM format with `\n`). | `-----BEGIN RSA PRIVATE KEY-----\n...` |
| **`GITHUB_WEBHOOK_SECRET`** | Shared secret configured in the GitHub App webhook settings. | `whsec_live_secret_string` |
| **`GITHUB_DEFAULT_ORGANIZATION_ID`** | Default organization UUID assigned to webhook-created analyses. | `00000000-0000-4000-8000-000000000001` |
| **`GITHUB_SINGLE_TENANT`** | `true` routes deliveries from installations not yet linked to an organization to `GITHUB_DEFAULT_ORGANIZATION_ID`. Safe only when one organization uses the App; default `false` rejects them (403). | `false` |
| **`GITHUB_PUBLISH_RESULTS`** | Whether the worker publishes Check Runs and PR comments to GitHub. | `true` |
| **`RADIUS_FEATURE_INTENT_INGESTION`** | IN-02, **off by default until the live GitHub validation (F-06)**; set `true` to enable. API: store the PR title and body from `pull_request` payloads as intent. Worker: when the GitHub App is configured, also fetch linked issues, commit messages and `.radius/intent.yml` for each new analysis and build the intent snapshot. Best-effort, never fails an analysis. Linked issues need the App permission `issues: read`; without it they are recorded as absent. Applies to both API and worker. | `false` |
| **`RADIUS_FEATURE_VERDICT_V2`** | Verdict v2 alpha (VD-07-lite), applies to API and worker. `off` (default; also unset, `false`, `0`, or any unrecognised value) runs no v2 code and `GET /analyses/{id}/verdict-v2` answers 404 `disabled`. `shadow` computes and stores v2 but keeps publishing v1. `on` (also `true`, `1`) publishes v2 when it succeeded and falls back to v1 otherwise. v1 is always computed and stored. Needs `RADIUS_FEATURE_INTENT_INGESTION=true` for a useful result; without an intent snapshot the verdict is `insufficient_evidence`. Design: `docs/research/design/VERDICT_V2_SLICE.md`. | `off` |
| **`RADIUS_INTENT_MAX_API_CALLS`**, **`RADIUS_INTENT_DEADLINE_SECONDS`** | Worker: hard cap on GitHub REST calls (default `15`) and wall-clock budget in seconds (default `30`) for intent ingestion of one analysis. | `15`, `30` |
| **`RADIUS_INTENT_ALLOW_CROSS_REPO`** | Worker: also fetch issues of OTHER repositories named by closing references (`owner/repo#n`). Off by default because the installation token can read every repository of the installation; skipped links are recorded as absent (`cross_repo_disabled`). | `false` |
| **`RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS`** | Worker: also fetch comments on linked issues and keep those by OWNER/MEMBER/COLLABORATOR humans as `comment` sources. One extra call per linked issue with comments. | `false` |
| **`RADIUS_TRACING_ENABLED`** | Enable OpenTelemetry tracing (needs the `observability` extra). Off by default. See `docs/OBSERVABILITY.md`. | `false` |
| **`RADIUS_OTLP_ENDPOINT`** | OTLP/HTTP traces endpoint; empty records spans without exporting. | `http://jaeger:4318/v1/traces` |
| **`RADIUS_METRICS_ENABLED`** | Expose Prometheus metrics at `/metrics` (API) and on the worker metrics port. Off by default. | `false` |
| **`RADIUS_WORKER_METRICS_PORT`** | Worker Prometheus port; `0` disables it. | `9100` |
| **`CORS_ORIGINS`** | API: comma separated browser origins allowed by CORS. In production every entry must be `https://host[:port]`; `*` is rejected at startup. Localhost dashboards are added automatically outside production. | `https://radius.yourcompany.com` |
| **`RADIUS_CORS_ALLOW_CREDENTIALS`** | API: send `Access-Control-Allow-Credentials` (session cookies). Never combined with `*`. | `true` |
| **`RADIUS_HSTS_ENABLED`** | API and dashboard: send `Strict-Transport-Security` (and CSP `upgrade-insecure-requests` on the dashboard). Enable only behind TLS. | `false` |
| **`RADIUS_MAX_BODY_BYTES`** / **`RADIUS_WEBHOOK_MAX_BODY_BYTES`** / **`RADIUS_UPLOAD_MAX_BODY_BYTES`** | API request body caps: default, GitHub webhook, CI test-report upload. Over the cap: `413 PAYLOAD_TOO_LARGE`. | `1048576` / `26214400` / `20971520` |
| **`RADIUS_TRUSTED_PROXIES`** | API: IPs/CIDRs of reverse proxies whose `X-Forwarded-For` is trusted for client-IP rate limiting. Empty trusts none (every client appears as the proxy). | `10.0.0.0/8` |
| **`RADIUS_RATE_LIMIT_ENABLED`** | API: master switch for the token-bucket limiter. | `true` |
| **`RADIUS_RATE_LIMIT_AUTH`** / **`_WEBHOOK`** / **`_GENERAL`** / **`_EXPENSIVE`** | API: `<requests>/<window seconds>` per bucket. In-memory, per replica. | `10/60`, `600/60`, `600/60`, `20/60` |
| **`RADIUS_RATE_LIMIT_IP_MULTIPLIER`** | API: per-IP limit as a multiple of the per-key limit for general/expensive buckets. | `2` |
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
   - **Issues**: Read (optional; only for linked-issue intent ingestion, `RADIUS_FEATURE_INTENT_INGESTION`; without it linked issues are recorded as absent)
3. Subscribe to Webhook Events:
   - `pull_request` (opened, synchronize, reopened)
   - `push`
4. Generate a Private Key, download the `.pem` file, and assign the content to `GITHUB_APP_PRIVATE_KEY`.
5. Install the App onto your organization's repositories.

---

## 5. Security & Isolation

- **Tenant Isolation**: Every API request requires an `X-Radius-Organization-Id` header (and optional Bearer API key). Data queries strictly scope records by organization ID.
- **Symlink Traversal Defense**: The worker uses `os.path.realpath` bounds checking during repository filesystem traversal to prevent symlink escape vulnerabilities.
- **No LLM on the verdict path**: the experimental semantic pruner is not invoked by the worker pipeline, so no model output can remove tests or dependency edges from the selection (see `docs/audit/RADIUS_AUDIT.md`). The `google-genai` and `google-generativeai` packages are still core dependencies (`pyproject.toml`) only because the legacy module imports them; moving them to an optional extra is a follow-up.
- **Code execution is off by default**: with `WORKER_TEST_EXECUTION_MODE=disabled` (default) worker analysis is static parsing and graph traversal and no repository code runs. The optional `sandbox` mode runs tests in an ephemeral hardened container and `unsafe_in_process` is refused in `uat`/`production`; see [security/EXECUTION_ISOLATION.md](security/EXECUTION_ISOLATION.md).
- **Third-party code egress**: nothing sends repository code to a third party by default. The only code-bearing path is the legacy Gemini pruner, which needs both `RADIUS_FEATURE_GEMINI_PRUNER=true` and `GEMINI_API_KEY`; leave them unset. Optional LLM intent extraction sends redacted intent text only (DEC-015/DEC-021).
