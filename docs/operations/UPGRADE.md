# Upgrade

Radius has no tagged releases yet (`CHANGELOG.md`: everything is under Unreleased), so "upgrade" means moving
your checkout to a newer commit of `develop`, `dev` or a future tag, rebuilding the images and applying
database migrations. Read the changelog fragments between the two versions first
(`git log --oneline OLD..NEW -- changelog.d CHANGELOG.md infra/database/migrations`).

## How migrations are applied

- Alembic, script location `infra/database/migrations` (`alembic.ini`), revisions
  `infra/database/migrations/versions/` (16 revisions at the time of writing, head `20261103_0016`).
- `infra/database/migrations/env.py` takes the URL from `DATABASE_URL` (falls back to `alembic.ini`) and normalises
  `postgres://` / `postgresql://` to `postgresql+psycopg://`.
- Compose runs a one-shot `migrations` service (`alembic upgrade head`) before `api` and `worker` start.
- The API image's default command is also `python -m alembic upgrade head && uvicorn ...`
  (`apps/api/Dockerfile`), so every API container start migrates.
- On startup the API additionally runs SQLAlchemy `metadata.create_all` for missing tables (domain and sign-in
  tables). That creates absent tables only and never alters existing ones; Alembic stays the authority for
  schema changes.

Consequence: starting a new API image against your database migrates it immediately. Back up first.

## Procedure

1. **Read the diff.** Note new migrations and any flag or variable changes. Regenerate your view of the
   settings with `python scripts/gen_config_reference.py` or read [CONFIGURATION.md](CONFIGURATION.md).
2. **Back up** the database ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)) and note the current revision:
   ```bash
   docker compose run --rm migrations alembic current
   ```
3. **Drain.** Optional but safer: `docker compose stop worker`. On SIGTERM the worker claims no new job and
   finishes the one it is running; the worker service has `stop_grace_period` 15 minutes
   (`WORKER_STOP_GRACE_PERIOD`) so Compose waits for that instead of killing it after 10 seconds. A job still
   running when the grace period ends is killed; it holds a lease that is renewed every
   `WORKER_HEARTBEAT_INTERVAL_SECONDS` while the worker lives, so after the kill it is recovered once the lease
   has been unrenewed for `WORKER_JOB_STALE_AFTER_SECONDS` (default 1800) and retried up to
   `WORKER_JOB_MAX_ATTEMPTS`. Several workers are safe: only the worker that claimed a job can complete, fail or
   requeue it. **Unverified** against a live PostgreSQL with several replicas.
   Upgrading from a version without `POSTGRES_PASSWORD`: the existing database volume keeps the old password
   (`radius`). Either set `POSTGRES_PASSWORD=radius` in `.env` (and change it in the database later) or, for a
   disposable dev stack, `make clean-volumes` and `make env`.
4. **Fetch and rebuild.**
   ```bash
   git fetch origin && git checkout <new commit or tag>
   docker compose --env-file .env build
   ```
5. **Migrate and start.**
   ```bash
   docker compose --env-file .env up -d
   docker compose logs migrations        # should end without error
   docker compose run --rm migrations alembic current     # should print the new head
   ```
6. **Verify.**
   ```bash
   docker compose ps                                  # services healthy
   curl -f http://localhost:8000/api/v1/ready         # database and queue reachable
   ```
   Then open one analysis in the dashboard, and re-run a recent pull request (`POST /analyses/{id}/rerun`
   or push a commit) and confirm the check run completes. Queue depth by status is on `/metrics` as
   `radius_queue_depth{status}` when `RADIUS_METRICS_ENABLED=true`.

## Rollback

Two options, in order of safety.

**A. Restore the backup (safest).** Stop `api` and `worker`, restore the dump taken in step 2
([BACKUP_RESTORE.md](BACKUP_RESTORE.md)), check out the old commit, rebuild and start. Use this whenever a
migration dropped or rewrote data.

**B. Alembic downgrade.** Every revision defines `downgrade()` (checked by reading the files), so a step back
is possible, but downgrades that drop a column or table destroy its contents and are not exercised in CI
(**Unverified**: a downgrade run on a populated database). Procedure:

```bash
docker compose stop api worker
docker compose run --rm migrations alembic downgrade <revision before the upgrade>   # or: -1
git checkout <old commit> && docker compose build && docker compose up -d
```

Never start the new API image against a downgraded database: its default command re-applies
`alembic upgrade head`.

Migrations `20261102_0013` and `20261102_0014` create the Verdict v2 alpha tables `verdict_v2` (stored bundles) and
`verdict_v2_requests` (the re-score outbox used after CI uploads). The tables exist even when the flag is `off`.
Downgrading past them drops those tables and their rows, which are derived data (v1 results are stored separately and are
unaffected), but still prefer a backup.

Migration `20261103_0016` creates `mutation_result_cache` (final mutant results per organization and repository, used only
with `RADIUS_FEATURE_MUTATION`, pruned after 30 days). The table exists even when the flag is off; downgrading drops it and
its rows, which are a pure cache.

## Compatibility notes for flags

- All `RADIUS_FEATURE_*` flags default off; upgrading never turns one on. After an upgrade, compare the
  Feature flags table in [CONFIGURATION.md](CONFIGURATION.md) with your `.env`.
- `RADIUS_FEATURE_VERDICT_V2` (alpha): `off` keeps v1 output unchanged (tests compare it); `shadow` stores v2 results but publishes v1;
  `on` publishes v2 and falls back to v1 on failure. It applies to **both** the API and the worker and
  needs `RADIUS_FEATURE_INTENT_INGESTION=true` to be useful. Set the same value on both services.
- `RADIUS_FEATURE_INTENT_INGESTION` must also match on both services (the API stores PR text from webhooks;
  the worker fetches issues, commits and `.radius/intent.yml`).
- `RADIUS_FEATURE_GEMINI_PRUNER` is new and off: the legacy Gemini pruner used to activate whenever
  `GEMINI_API_KEY` was set in the process environment. It is not on the live analysis path either way.
- `WORKER_EXECUTE_TESTS` is deprecated. When `WORKER_TEST_EXECUTION_MODE` is unset, `WORKER_EXECUTE_TESTS=true`
  still maps to `unsafe_in_process`, which the worker refuses to start with in `uat`/`production` unless
  `RADIUS_ALLOW_UNSAFE_EXECUTION=true` ([EXECUTION_ISOLATION.md](../security/EXECUTION_ISOLATION.md)).
- Review partials (DEC-040): migration `20261104_0021` adds `auth_accounts.provider_login` (nullable). Users who signed in
  with GitHub before the upgrade are treated as "GitHub link unknown" until their next GitHub sign-in. Set the same
  `RADIUS_VERDICT_V2_CONFIRM_POLICY` (`allow_unverified` default, or `require_second_person`) on the worker. The dashboard now
  sends `X-Radius-Session` to the API on intent writes; keep that hop private. In uat/production the verify-email page asks for
  a password and signup no longer answers 409 for a registered address.
- The 0-100 confidence score is labelled `heuristic_uncalibrated` and is not a probability; do not build
  gates on it.
- Pre-1.0: `0.y.z` may change anything. There is no stated API compatibility promise yet.

## Dashboard and images

Next.js normally inlines `NEXT_PUBLIC_*` values into browser code at build time. The dashboard Dockerfile
declares no build argument for them (only `RADIUS_VERSION` and `VCS_REF`) while Compose passes them at runtime, so
**Unverified:** whether changing `NEXT_PUBLIC_RADIUS_API_BASE_URL` takes effect in the browser without a rebuild.
After changing them, rebuild (`docker compose build dashboard`) and check the browser network tab. The
server-side proxy variables (`RADIUS_API_BASE_URL`, `RADIUS_API_KEY`) are read at runtime.
Named volumes created by an older root-owned image keep root ownership:
recreate the repository cache volume or `chown -R 10001:10001` it
([security/CONTAINERS.md](../security/CONTAINERS.md)).
