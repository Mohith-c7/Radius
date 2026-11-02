# Install (Docker Compose)

This is the only supported install path today. There are no published images, Helm chart or
release artifacts; the images are built from your checkout. **Unverified:** a clean-machine run of
this exact procedure was not performed while writing this page (no Docker build was run); the steps
come from `Makefile`, `docker-compose.yml`, the Dockerfiles and the code.

## Prerequisites

| Need | Detail |
|---|---|
| Docker with Compose v2 | `docker compose config -q` parsed the shipped `docker-compose.yml` with Compose 5.3.1. Older v2 releases: unverified |
| git | To clone the repository |
| Free host ports | `3000` (dashboard), `8000` (API), `5432` (PostgreSQL; change with `POSTGRES_HOST_PORT`) |
| Time | The first build takes several minutes (README cites about 10 on a cold cache); later starts are faster |
| Optional: GNU make | `make dev`. On Windows without make use `.\scripts\dev.ps1 dev` |
| Optional: a GitHub App | Needed to analyse real pull requests, see [DEPLOYMENT.md](../DEPLOYMENT.md) section 4 |

Disk, RAM and CPU sizing: **Unverified**, nothing in the repository measures it. The bundled PostgreSQL is
`postgres:16-alpine` with data in the named volume `radius-postgres-data`.

## Steps

```bash
git clone https://github.com/Mohith-c7/Radius.git && cd Radius
make dev          # or: .\scripts\dev.ps1 dev
```

`make dev` copies `.env.example` to `.env` if it does not exist (it never overwrites), appends
`GITHUB_DEFAULT_ORGANIZATION_ID`, then runs
`docker compose --env-file .env up --build -d --wait --wait-timeout 300 postgres migrations api worker dashboard`.
Compose starts PostgreSQL, runs the one-shot `migrations` service (`alembic upgrade head`), then the
API, worker and dashboard once their dependencies are healthy.

Without make:

```bash
cp .env.example .env
docker compose --env-file .env up --build -d
```

Check it:

```bash
docker compose ps                       # api, worker, dashboard, postgres should report healthy
curl -f http://localhost:8000/api/v1/health
curl -f http://localhost:8000/api/v1/ready      # 503 if the database is unreachable
```

Open the dashboard at http://localhost:3000 and the API docs at http://localhost:8000/docs.

## First-run settings you must understand

The Compose `api` and `worker` services run with `RADIUS_ENV=production` regardless of your `.env`
(`docker-compose.yml`). In production mode the API fails closed:

- `RADIUS_ALLOW_INSECURE_DEV` is honoured only in `development`/`test` and is not forwarded by
  Compose, so the keyless dev shortcut does not apply to the Compose stack.
- **API keys.** Protected routes answer 403 `ACCESS_DENIED` ("Radius API keys are not configured")
  until `API_KEYS` holds at least one `org_id:key` pair (`apps/api/src/radius_api/auth.py`). Set, in `.env`:

  ```
  API_KEYS=00000000-0000-4000-8000-000000000001:<long random key>
  RADIUS_API_KEY=<the same key>
  NEXT_PUBLIC_RADIUS_ORGANIZATION_ID=00000000-0000-4000-8000-000000000001
  GITHUB_DEFAULT_ORGANIZATION_ID=00000000-0000-4000-8000-000000000001
  ```

  `RADIUS_API_KEY` is the server-side secret the dashboard proxy sends; it is never given a
  `NEXT_PUBLIC_` prefix. The org id must match between `API_KEYS` and the dashboard variable.
  **Unverified:** that the dashboard works end to end with exactly these values on a fresh database.
- **Webhooks.** `GITHUB_WEBHOOK_SECRET` is mandatory; unsigned deliveries get 403.
- **Dashboard sign-in.** Accounts are auto-verified only when `RADIUS_ENV=development` or
  `DEV_AUTO_VERIFY_EMAIL=true` (`apps/api/src/app/auth.py`). For a local evaluation set
  `DEV_AUTO_VERIFY_EMAIL=true` in `.env`; otherwise configure `SMTP_*` so verification mail can be sent.
  Never leave auto-verify on for a shared deployment.
- **Session secret.** Set `SESSION_SECRET` (32+ characters). If it is unset, Compose falls back to the
  placeholder that is public in the source; the value in `.env.example` is also only a placeholder.
- **Demo data.** `RADIUS_SEED_DEMO_DATA` is ignored in production mode. Use `make seed-demo` against a
  disposable database if you want illustrative data.

Compose forwards only the variables listed in `docker-compose.yml`. Anything else in
[CONFIGURATION.md](CONFIGURATION.md) needs a line in the service `environment:` block.

## Connect GitHub

Create a GitHub App, set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` (and
`GITHUB_INSTALLATION_ID` or `GITHUB_SINGLE_TENANT=true` plus `GITHUB_DEFAULT_ORGANIZATION_ID` for a single
organization), expose the API over HTTPS and point the App webhook at
`https://<api host>/api/v1/webhooks/github`. Permissions and events are in
[DEPLOYMENT.md](../DEPLOYMENT.md) section 4 and the validation checklist is
[github-app-validation/RUNBOOK.md](../github-app-validation/RUNBOOK.md). Note that linked-issue intent
ingestion additionally needs the `issues: read` permission (RUNBOOK section 0).

## What the first verdict looks like

Test execution inside the worker is off by default (`WORKER_TEST_EXECUTION_MODE=disabled`), so a first
pull request normally ends `insufficient_evidence` with the gap "Selected tests were not executed; upload
CI results to verify" (`packages/confidence/.../scoring.py`). To reach `verified`, run the selected tests in
your CI and upload JUnit XML or JSON bound to the head SHA ([CI integration](../CI_INTEGRATION_GUIDE.md)).
The check run is not re-published after a later upload (README, maturity table).

## Optional profiles

| Profile | Command | Purpose |
|---|---|---|
| `sandbox` | `docker compose --profile sandbox up sandbox-image` | Builds the test image only. The Compose worker has no container runtime, so sandbox execution is not available inside Compose ([security/CONTAINERS.md](../security/CONTAINERS.md)) |
| `observability` | `docker compose --profile observability up -d jaeger prometheus` | Jaeger (UI on 16686, OTLP on 4318) and Prometheus (9090). Also set `RADIUS_TRACING_ENABLED` / `RADIUS_METRICS_ENABLED`, see [OBSERVABILITY.md](../OBSERVABILITY.md) |

## Stop and reset

```bash
make down                     # keeps the database volume
docker compose down -v        # also deletes radius-postgres-data and radius-repository-cache (all data)
```
