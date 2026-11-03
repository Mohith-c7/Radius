# Runbook

Symptom, then checks, then action, for a running Compose stack. Service names are the Compose names (`api`,
`worker`, `dashboard`, `postgres`). Replace `docker compose` with your orchestrator's equivalent. SQL runs with:

```bash
docker compose exec postgres psql -U radius -d radius
```

Logs are one JSON object per line with `request_id`, `delivery_id`, `organization_id`, `analysis_id`, `job_id`
where known ([OBSERVABILITY.md](../OBSERVABILITY.md)). Anything marked **Unverified** was derived from reading the
code, not from an incident.

## Quick health

```bash
docker compose ps                                   # STATUS should say healthy
curl -s  http://localhost:8000/api/v1/health        # liveness (no dependencies)
curl -si http://localhost:8000/api/v1/ready         # 200, or 503 not_ready if database/queue unreachable
docker compose logs --tail 100 worker api
```

The worker has no HTTP port; its container health is "can it run `select 1` against the database". A hung poll loop
is **not** detected by that check (noted in `apps/worker/Dockerfile`). Use queue depth (below) to notice a stalled worker.
With `RADIUS_METRICS_ENABLED=true`: API `/metrics`, worker `RADIUS_WORKER_METRICS_PORT`; metrics
`radius_queue_depth{status}`, `radius_job_duration_seconds`, `radius_job_retries_total`,
`radius_stage_failures_total{stage}`, `radius_sandbox_kills_total`, `radius_http_rate_limited_total{bucket}`.

## Queue stuck: analyses stay pending or running

Checks:

```sql
select status, count(*) from analysis_jobs group by 1;      -- pending / running / completed / failed
select analysis_id, status, attempts, locked_at, left(last_error, 120)
  from analysis_jobs where status in ('pending','running') order by created_at limit 20;
select status, count(*) from analyses group by 1;           -- adds cancelled
```

| Observation | Meaning | Action |
|---|---|---|
| Many `pending`, none `running` | No worker is polling | `docker compose ps worker`; `docker compose logs worker`. Start it. A worker that cannot start logs the reason (for example `SandboxMisconfiguredError`, `UnsafeExecutionRefusedError`) |
| `running` with an old `locked_at` | The worker died mid-job | Nothing to do: a job `running` longer than `WORKER_JOB_STALE_AFTER_SECONDS` (default 1800) is returned to `pending`, or `failed` when `attempts` reached `WORKER_JOB_MAX_ATTEMPTS` (default 3) |
| Analysis `pending`/`running` for longer than `WORKER_ANALYSIS_DEADLINE_SECONDS` (default 7200) | Lost job or very slow run | The reaper (every `WORKER_REAPER_INTERVAL_SECONDS`, 60) marks the analysis `failed` and completes the GitHub check run so it is not left in progress |
| `pending` is only growing | Worker slower than arrivals | One worker polls every `WORKER_POLL_INTERVAL_SECONDS` (2); see whether `radius_job_duration_seconds` is long. Scaling to several worker replicas: **Unverified** (the queue uses leases, `claim_next`, but multi-worker behavior was not tested) |

Re-run one analysis: `POST /api/v1/analyses/{id}/rerun` (needs the org and API key headers), or push a commit.

## Jobs failing

```sql
select analysis_id, attempts, left(last_error, 300) from analysis_jobs where status = 'failed' order by updated_at desc limit 20;
```

- `last_error` and the worker log line with the same `analysis_id` give the exception. A job is retried until
  `attempts` reaches `WORKER_JOB_MAX_ATTEMPTS`, then stays `failed` and the analysis becomes `failed`.
- `radius_stage_failures_total{stage}` shows which pipeline stage fails.
- Clone failures: check `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` and that the App is installed on the repository;
  the worker authenticates `git` with an installation token. Check the cache volume is writable by uid `10001`.
- `GITHUB_INSTALLATION_ID or organization.github_installation_id is required`: neither the fixed id nor a stored
  installation exists for that organization (`apps/worker/.../runner.py`). Connect the installation or set the id.
- Fix the cause, then rerun. Failed analyses are not retried automatically after `failed`.
- Optional steps are best-effort: intent ingestion (`RADIUS_FEATURE_INTENT_INGESTION`) and the flagged-off steps log and
  continue; their failure does not fail the analysis.

## Webhooks return 4xx

Find the delivery in the GitHub App settings (Advanced, Recent Deliveries); redeliver after fixing. API behavior
(`routes/github_webhooks.py`, `main.py`, middleware):

| Status | Cause | Fix |
|---|---|---|
| 403 `ACCESS_DENIED` "webhook secret is not configured" | `GITHUB_WEBHOOK_SECRET` empty in production | Set it on `api` |
| 403 "Missing"/"Invalid GitHub webhook signature" | Secret differs from the GitHub App's, or a proxy altered the body | Make the secrets identical; the signature is HMAC-SHA256 over the raw bytes, so do not re-encode the body in a proxy |
| 403 "Unknown GitHub installation" | Installation not linked to an organization and `GITHUB_SINGLE_TENANT` is false | Connect it to an organization, or for a single org set `GITHUB_SINGLE_TENANT=true` and `GITHUB_DEFAULT_ORGANIZATION_ID` |
| 422 `VALIDATION_ERROR` "GITHUB_DEFAULT_ORGANIZATION_ID is required" | Single-tenant without a default org | Set `GITHUB_DEFAULT_ORGANIZATION_ID` |
| 413 `PAYLOAD_TOO_LARGE` | Body over `RADIUS_WEBHOOK_MAX_BODY_BYTES` (5 MiB default; GitHub allows up to 25 MiB) | Raise the cap only if a genuine delivery was refused; otherwise it is an unauthenticated caller |
| 429 | Webhook bucket (`RADIUS_RATE_LIMIT_WEBHOOK`, 600/60 per client IP) exhausted, often because `RADIUS_TRUSTED_PROXIES` is unset so GitHub traffic shares the proxy IP | Set `RADIUS_TRUSTED_PROXIES`; raise the limit; `Retry-After` is returned |
| 202 with `ignored: true` | Not an error: draft or non-analysed action, `installation_deleted`, `installation_suspended`, `repository_disconnected` | See the event table in [github-app-validation/RUNBOOK.md](../github-app-validation/RUNBOOK.md) section 0 |
| 502/504 from your proxy | API down or slow | Check `api` health and logs |

No delivery reaches the API at all: check the App's webhook URL (`https://<host>/api/v1/webhooks/github`), TLS validity
and that your proxy forwards the path.

## GitHub rate limits and API errors

- The GitHub client (`packages/github/src/radius_github/client.py`) has **no specific rate-limit handling** (no
  `Retry-After` / `x-ratelimit-*` logic was found in it). A 403 or 429 from GitHub surfaces as an error in
  the worker log for that step. Whether such a publish failure fails the whole job is **Unverified**; check
  `last_error` and the log.
- Intent ingestion is capped per analysis: `RADIUS_INTENT_MAX_API_CALLS` (15), `RADIUS_INTENT_DEADLINE_SECONDS` (30), and
  optional comment fetching is off. If you hit limits, leave `RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS` off and lower the caps.
- Installation tokens have GitHub-side hourly limits (GitHub documentation, not verified here); busy organizations
  with many pushes per hour may hit them. Reduce triggers or request a higher limit from GitHub.
- Wrong API version or base URL: `GITHUB_API_VERSION` (default `2026-03-10`) and `GITHUB_API_BASE_URL` (set for GitHub
  Enterprise Server).
- Check runs missing or stuck in progress: the worker completes in-progress check runs on failure and the reaper completes them
  for expired analyses. If a check never appears, confirm `GITHUB_PUBLISH_RESULTS=true` and that App id and key are set on the **worker**.
- Check run shows `insufficient_evidence` after CI passed: expected until results are uploaded, and the check is not
  re-published after a later upload (README).

## Sandbox (test execution) failures

Only relevant when `WORKER_TEST_EXECUTION_MODE=sandbox`; with the default `disabled` nothing executes.

| Symptom | Cause | Action |
|---|---|---|
| Worker exits at startup with `SandboxMisconfiguredError` | Runtime binary or daemon unavailable, image not pulled locally, bad limits, `unconfined` or missing seccomp profile | Fix the named item. The worker never falls back to another mode. The Compose worker image has no container runtime: use the `sandbox` image target and give it a daemon ([security/CONTAINERS.md](../security/CONTAINERS.md)) |
| Worker exits at startup with `UnsafeExecutionRefusedError` | `unsafe_in_process` (or legacy `WORKER_EXECUTE_TESTS=true`) in `uat`/`production` | Switch to `disabled` or `sandbox` |
| Test run result `error`, "sandbox unavailable, refusing to execute" | Daemon or image vanished after startup | Restore the runtime or image; nothing was executed |
| `error` with exit 137/152/153, timeout or output cap | OOM kill, CPU/file-size limit, or `WORKER_TEST_TIMEOUT_SECONDS` / `WORKER_SANDBOX_MAX_OUTPUT_BYTES` exceeded | Raise the matching limit deliberately; see `radius_sandbox_kills_total` |
| Tests fail on missing packages | The sandbox has no network and the image must already contain the toolchain and project dependencies | Build and pin an image that has them (`WORKER_SANDBOX_IMAGE`) |

Any of these yields no `passed` evidence, so the verdict stays `insufficient_evidence` or `failed`, never `verified`.

## Disk

```bash
docker system df
docker compose exec postgres psql -U radius -d radius -c "select pg_size_pretty(pg_database_size('radius'));"
docker compose exec postgres psql -U radius -d radius -c "select relname, pg_size_pretty(pg_total_relation_size(oid)) from pg_class where relkind='r' order by pg_total_relation_size(oid) desc limit 10;"
docker compose exec worker du -sh /var/lib/radius/repositories
```

- Repository cache (`radius-repository-cache`): rebuildable. Stop the worker, remove the volume, start it; clones are
  recreated on demand.
- PostgreSQL: no automatic retention exists ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)); the largest tables are the
  graph and test tables (`graph_nodes`, `graph_edges`, `test_cases`, uploads). Deleting rows by hand risks
  referential damage: back up first. The opt-in `RADIUS_RETENTION_DAYS` task prunes only `idempotency_keys`, exhausted `verdict_v2_requests` and
  `mutation_result_cache`; no job prunes the graph, test, analysis or verdict tables.
- Container logs: configure the Docker logging driver size limits; the default json-file driver is unbounded.
- A full PostgreSQL volume makes `/api/v1/ready` return 503 and jobs fail; free space, then restart.

## Migrations

```bash
docker compose logs migrations
docker compose run --rm migrations alembic current
docker compose run --rm migrations alembic heads         # exactly one head expected
docker compose run --rm migrations alembic history | head
```

| Symptom | Cause | Action |
|---|---|---|
| `migrations` service exited non-zero, `api` never starts | Database unreachable, wrong `DATABASE_URL`, or a failing revision | Read its log; fix the connection or the data issue, rerun `docker compose up -d` |
| `Can't locate revision ...` | Database stamped by a newer version than the code | Check out the newer code, or restore a backup taken before the upgrade ([UPGRADE.md](UPGRADE.md)) |
| `Multiple head revisions` | Two branches added migrations | A development issue; report it, do not stamp over it |
| Tables exist but `alembic current` is empty | The schema was created by `create_all` (API startup) without Alembic | `alembic stamp` is **not** safe to guess; compare with a fresh database or restore from backup. **Unverified** procedure |

## Escalate with

Version (`git rev-parse HEAD`), `docker compose ps`, relevant log lines with `request_id` / `analysis_id`, the
queue SQL output, `alembic current`, and your non-secret configuration. Never paste values of secret variables
(marked in [CONFIGURATION.md](CONFIGURATION.md)). Vulnerabilities go through [SECURITY.md](../../SECURITY.md).
