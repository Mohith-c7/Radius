# Deployment

This document covers the Phase 1 production runtime shape for Radius.

## Services

- `postgres`: PostgreSQL 16 database.
- `migrations`: one-shot Alembic migration runner.
- `api`: FastAPI service exposed on port `8000`.
- `worker`: SQL-backed analysis worker.
- `dashboard`: Next.js dashboard exposed on port `3000`.

## Local Production Smoke Test

```bash
docker compose up --build
```

Then check:

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
```

The dashboard is available at `http://localhost:3000`.

## Required Environment

Set these before running a real deployment:

- `DATABASE_URL`: PostgreSQL connection string for API, worker, and migrations.
- `API_KEYS`: comma-separated API keys accepted by the API.
- `GITHUB_WEBHOOK_SECRET`: shared secret configured on the GitHub webhook.
- `GITHUB_DEFAULT_ORGANIZATION_ID`: default organization UUID for webhook-created analyses.
- `GITHUB_APP_ID`: GitHub App id used to create installation tokens.
- `GITHUB_APP_PRIVATE_KEY`: PEM private key for the GitHub App. Use escaped
  `\n` line breaks when storing in a single-line secret.
- `GITHUB_INSTALLATION_ID`: optional fallback installation id. Webhook payloads
  can also persist `installation.id` onto the organization.
- `GITHUB_PUBLISH_RESULTS`: set to `false` only for local smoke tests where
  GitHub publishing should be skipped.
- `DASHBOARD_BASE_URL`: public dashboard URL used in GitHub Check Runs and PR
  comments.
- `NEXT_PUBLIC_RADIUS_API_BASE_URL`: browser-visible API base URL.
- `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID`: organization UUID used by the dashboard.
- `NEXT_PUBLIC_RADIUS_API_KEY`: dashboard API key if API key enforcement is enabled.

For production, replace the compose defaults with managed secrets and a managed
PostgreSQL instance. Do not use the sample `radius/radius` database credentials.

## CI

`.github/workflows/ci.yml` validates pull requests and protected branches by
running:

- `pnpm install --frozen-lockfile`
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- `pnpm build`
- `alembic upgrade head`

The migration sanity step runs against a PostgreSQL service container.

## GitHub App Permissions

Configure the GitHub App with:

- Repository contents: read
- Pull requests: read
- Checks: read/write
- Issues: write
- Metadata: read

Subscribe it to `pull_request`, `push`, and `ping` webhook events.
