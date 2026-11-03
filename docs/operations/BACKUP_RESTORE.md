# Backup and restore

Radius keeps its durable state in one PostgreSQL database. Nothing else needs a backup to recover the
service, apart from your own configuration and secrets. Commands below assume the Compose stack
(service `postgres`, database, user and password all `radius` in `docker-compose.yml`; change them for any
real deployment). **Unverified:** the dump/restore commands were not executed while writing this page.

## What is stored where

| Data | Location | Back up? |
|---|---|---|
| Organizations, repositories, pull requests, analyses, the job queue (`analysis_jobs`), graph snapshots, test selections and uploaded results, confidence reports, intent sources, snapshots and criteria, idempotency keys | PostgreSQL, database from `DATABASE_URL` | Yes, this is the system of record |
| Dashboard sign-in tables (users with password hashes, sessions) | Same database when `DATABASE_URL` is set. If it is unset the sign-in module falls back to a local SQLite file `./radius.db` (`apps/api/src/app/config.py`) | Yes; set `DATABASE_URL` so it is not on a container filesystem |
| Repository clones | Volume `radius-repository-cache` mounted at `/var/lib/radius/repositories` (`REPOSITORY_CACHE_DIR`) | No, it is a rebuildable cache (docs/DEPLOYMENT.md) |
| Rate-limit buckets, LLM token ledger and response cache | Process memory | No, lost on restart by design |
| `STORAGE_BACKEND=memory` data | Process memory (default when the variable is unset; Compose sets `sql`) | Not recoverable; use `sql` |
| Configuration and secrets (`.env`, GitHub App private key, `API_KEYS`, `SESSION_SECRET`) | Your secret store / `.env` | Yes, separately and encrypted. They are not in the database dump |
| GitHub-side state (check runs, PR comments) | GitHub | n/a |

A dump contains repository metadata, PR text, symbol names and file paths, password hashes and session rows.
Treat it as sensitive: encrypt it at rest, restrict access, and do not attach it to tickets.

## Backup

Logical dump in custom format (compressed, restorable selectively):

```bash
docker compose exec -T postgres pg_dump -U radius -d radius -Fc > radius-$(date +%Y%m%d-%H%M%S).dump
```

Against an external PostgreSQL use the same flags with `-h`, `-p` and a credentials file (`PGPASSFILE`) rather
than a password on the command line.

Record the schema revision next to the dump, because a restore must be matched to a compatible code version:

```bash
docker compose run --rm migrations alembic current > radius-<same stamp>.revision
```

Verify a dump is readable (does not touch the database):

```bash
pg_restore --list radius-<stamp>.dump | head
```

Volume-level snapshots of `radius-postgres-data` are possible but only consistent when PostgreSQL is stopped
or snapshotted atomically; prefer `pg_dump`.

## Restore

Into the same or an empty database, with the application stopped so nothing writes during the restore:

```bash
docker compose stop api worker dashboard
docker compose exec -T postgres pg_restore -U radius -d radius --clean --if-exists --no-owner < radius-<stamp>.dump
docker compose run --rm migrations alembic current        # should match the recorded revision
docker compose up -d
curl -f http://localhost:8000/api/v1/ready
```

To restore into a brand-new database: create it first (`createdb` / `CREATE DATABASE radius`), point
`DATABASE_URL` at it, restore, and start the services.

Check after a restore: `alembic current` equals the stamped revision (or `alembic upgrade head` brings it forward),
`select status, count(*) from analysis_jobs group by 1;` looks plausible, and one analysis opens in the
dashboard. Jobs that were `running` when the dump was taken are recovered by the worker after
`WORKER_JOB_STALE_AFTER_SECONDS`; GitHub deliveries missed during the outage are not replayed automatically
(redeliver from the GitHub App advanced settings, or push a commit).

## Retention

- **Code:** no automatic pruning of analyses, verdicts, uploads or graph snapshots exists; those are never deleted by
  Radius. One opt-in worker task, `RADIUS_RETENTION_DAYS` (default 0 = off, minimum 7), deletes only expired rows of
  three disposable tables: `idempotency_keys`, exhausted `verdict_v2_requests` outbox rows (completed requests are
  already deleted on success) and `mutation_result_cache`. It runs hourly in batches; set `RADIUS_RETENTION_DRY_RUN=true`
  first to see in the worker log how many rows it would delete. The rest of the database grows with use; plan disk
  and monitor it ([RUNBOOK.md](RUNBOOK.md)).
- **Backups:** the schedule is yours. A common starting point (a recommendation, not something Radius enforces):
  daily dumps kept 7 days, weekly kept 4, one monthly kept 6, plus a dump before every upgrade. Test a restore on
  a scratch database at least once per quarter.
- **Privacy:** a data-retention and privacy policy for Radius itself is not written yet (task QS-06 and PRD-29 in
  the backlog). Until then deleting a customer's data means deleting rows by hand.
- **Disaster recovery targets (RPO/RTO):** none defined (task QS-11 is open).
