# Code review C: worker, database, dashboard and CI on `origin/develop` (45a9bcf)

Scope: worker and job queue, database models and Alembic history, dashboard (proxy, middleware, headers), CI/CD, Docker/Compose, docs versus code.
Method: code reading plus small repros with `D:/nuclei/worktrees/.venv-radius` (no suites, no Docker, no network). Docs, PR bodies and commit messages were not trusted. Reviews A (security) and B (Verdict v2) were read first; their findings are not repeated (C-12 only extends A-05).
Confidence: **confirmed** = I ran a repro; **reading** = careful reading of the cited lines; **suspected** = plausible, not exercised.

## Summary table

| Id | Severity | Confidence | Location | One line |
|----|----------|-----------|----------|----------|
| C-01 | high | reading | apps/dashboard/middleware.ts:28-31; app/api/radius/[...path]/route.ts:19-52; lib/proxy.ts:44-53,100-111 | The dashboard proxy accepts ANY non-empty `radius_session` cookie and then acts with the shared server-side API key (read, write, DELETE); all users share one org |
| C-02 | high | reading | packages/analysis/src/radius_analysis/infrastructure/sqlalchemy_job_queue.py:139,326-348,360-369; apps/worker/src/radius_worker/runner.py:229-311 | No lease renewal or owner check: a job running past `WORKER_JOB_STALE_AFTER_SECONDS` (30 min) is re-claimed by another replica while the first still runs |
| C-03 | high | reading | packages/repository/src/radius_repository/infrastructure/local_git.py:26-52; runner.py:640-658,707-713 | One shared working tree per repository and no lock: replicas analysing two PRs of one repo `git checkout` over each other and score the wrong tree |
| C-04 | medium | reading | runner.py:232-308; packages/analysis/.../sqlalchemy_store.py:113-138 | The whole analysis is one DB transaction held for the job's lifetime: "running" is invisible, the row stays locked, the GitHub result is published before the commit |
| C-05 | medium | reading | sqlalchemy_job_queue.py:117-143,224-239; runner.py:442-451 | Retries have no backoff: a short outage burns all 3 attempts within seconds and the poller never retries a failed head |
| C-06 | medium | reading | local_git.py:118-125,133-139 | `git clone/fetch/checkout` run with no timeout: a hung git hangs the worker, then triggers C-02 |
| C-07 | medium | reading | local_git.py:30-52; runner.py:640-658 | The repository cache is never pruned or gc'd; `git checkout` has no detach/force/clean; a stale `index.lock` wedges one repository |
| C-08 | low | confirmed (path arithmetic) | runner.py:707-719 | `_safe_path_segment` keeps `.`: owner `..` puts the checkout outside `REPOSITORY_CACHE_DIR` |
| C-09 | medium | reading | docker-compose.yml (no `stop_grace_period`, no `restart:`); runner.py:116-128; apps/worker/Dockerfile:79-80 | Graceful shutdown is defeated by Compose's 10 s kill; no restart policy; worker healthcheck cannot see a wedged loop |
| C-10 | low | reading | docker-compose.yml:118-153 vs docs/operations/CONFIGURATION.md:89 | Compose does not forward worker settings the docs tell operators to set (`RADIUS_RETENTION_DAYS`, mutation, `RADIUS_INTENT_EXTRACTION_MODE`) |
| C-11 | medium | reading | apps/api/src/radius_api/routes/analyses.py:98-140; sqlalchemy_store.py:58-83,205-209; routes/repositories.py:202-216 | `GET /analyses` is N+1 and unbounded (all analyses of all repos with changed files); the PR list is unbounded |
| C-12 | medium | reading | packages/shared/src/radius_shared/database/models.py:111-115,211-268; packages/analysis/.../services.py:68-76; sqlalchemy_store.py:37-56 | No unique constraint on (pull_request_id, commit_sha): `find_active` is check-then-insert, so concurrent triggers create duplicate analyses and jobs |
| C-13 | medium | reading | apps/api/src/radius_api/main.py:104-107; apps/api/src/app/models.py; infra/database/migrations/env.py:5 | Auth tables exist only via `create_all`: no Alembic history, so any later column change never reaches an existing database; sessions/tokens never purged |
| C-14 | medium | confirmed | apps/api/src/app/database.py:8; app/config.py:19 | The auth engine does not normalise `DATABASE_URL`: `postgres://` crashes the API at import although Alembic and the worker accept it; no `pool_pre_ping`; second pool |
| C-15 | low | confirmed (alembic compare) | models.py:85-89 vs migration 20260729_0001:91 | Model says `users.github_user_id` is nullable, the migrated column is NOT NULL (and the code fabricates an id from the e-mail hash) |
| C-16 | low | reading | .github/workflows/release.yml:140-215 | Publish has no protected `environment`; the pushed image is a second build, not the scanned one; any `v*` tag on any branch enters the path |
| C-17 | low | reading | apps/api/Dockerfile (CMD); docker-compose.yml:36-44 | Every API container start runs `alembic upgrade head`; concurrent starts race (no migration lock) |
| C-18 | low | reading | apps/worker/src/radius_worker/config.py:25-37 | No bounds on `job_max_attempts`, `job_stale_after_seconds`, `analysis_deadline_seconds`; `0` silently stops all processing |
| C-19 | low | reading | docs/KNOWN_LIMITATIONS.md:31-33; docs/operations/RUNBOOK.md:87-88; docs/operations/UPGRADE.md:31-32 | Docs contradict the code (no SSO, no DAST, no rate-limit handling, "leased" jobs, "drain" by `compose stop`) |
| C-20 | low | suspected | apps/api/src/app/routes_auth.py:102-110; apps/dashboard/middleware.ts:28 | Session cookie is host-only (no `Domain`): a dashboard on another host than the API never sees it and loops to `/login` |
| C-21 | low | reading | docker-compose.yml:23,42,61,121,96,174 | Hard-coded `radius/radius` DB credentials in the "production-like" compose (not overridable from `.env`); API and dashboard bind 0.0.0.0 |

## Findings in detail

### C-01 (high, reading): dashboard proxy trusts the mere presence of a cookie

- `apps/dashboard/middleware.ts:28` sets `hasSession = Boolean(request.cookies.get("radius_session")?.value)`. Lines 29-31 return 401 for `/api/radius/*` only when that is false (and `NODE_ENV !== "development"`). Nothing validates the value.
- `app/api/radius/[...path]/route.ts:19-52` forwards the request with `buildUpstreamHeaders` (`lib/proxy.ts:100-111`), which adds `X-Radius-API-Key` and `X-Radius-Organization-Id` from the server environment. The only session validation is client-side (`components/auth-provider.tsx`, `GET /auth/me` from the browser), which the proxy never consults.
- Scenario: anyone who can reach port 3000 (`docker-compose.yml:174` publishes it on all interfaces) runs `curl -H 'Cookie: radius_session=x' http://host:3000/api/radius/repositories`. That reads the configured organization's repositories, analyses, verdicts and intent. The allowlist (`lib/proxy.ts:8-34`) also lets them `DELETE repositories/{id}`, `POST repositories/connect-github`, `POST analyses/{id}/rerun`, upload test results and write/confirm intent criteria. A signed-out or revoked user keeps access with any leftover cookie.
- Even for a genuinely signed-in user the proxy is single-tenant: every user (including a self-signup, see A-07) sees the one org in `RADIUS_ORGANIZATION_ID`, not the workspace created for them at sign-up (`provision_domain_user_and_org`).
- Related: the audit actor of intent writes (`X-Radius-Actor`, `lib/proxy.ts:108-109`) is taken from a client header, so audit attribution is client-chosen rather than the signed-in identity.
- Fix: validate the cookie against the API (`GET /auth/me`, cached for a few seconds) inside the proxy route and in the middleware before forwarding; derive organization and actor from the validated user, not from env; never use cookie presence as authentication.

### C-02 (high, reading): no lease renewal, no ownership check on completion

- `claim_next` sets `locked_at` once (`sqlalchemy_job_queue.py:139`). Nothing refreshes it (no heartbeat code exists in the repository). `recover_stale_jobs` (`:326-348`) returns any RUNNING job with `locked_at` older than `job_stale_after_seconds` (default 1800) to PENDING, or marks it FAILED when attempts are exhausted.
- The worker runs a job synchronously (`runner.py:229-311`). Legitimate jobs can exceed 30 minutes: tests are bounded per command by `WORKER_TEST_TIMEOUT_SECONDS` (600) times `1 + WORKER_TEST_RERUNS`, plus mutation (`RADIUS_MUTATION_WALL_CLOCK_SECONDS`, 600), clones of large repositories, GitHub calls.
- Scenario (two or more worker replicas): replica B's `claim_next` calls `recover_stale_jobs`, flips A's still-running job to PENDING, claims it (attempt 2) and starts a second full run of the same analysis, with a second in-progress check run and a second publication. `complete`, `fail` and `requeue` look the job up by `analysis_id` only (`:360-369`), so whichever finishes last overwrites the other's outcome. One replica is not affected by this path (recovery only runs when the same process asks for work), so it is the multi-replica case that KNOWN_LIMITATIONS.md:37 calls "documented from code, not run".
- Fix: renew `locked_at` from a heartbeat thread (or between pipeline stages), store a claim token and make `complete/fail/requeue` conditional on it (`UPDATE ... WHERE claim_token = :t`), and abort the pipeline when the token is lost.

### C-03 (high, reading): one shared working tree per repository

- `_repository_cache_path` (`runner.py:707-713`) is `cache/<owner>/<name>-<github_repository_id>`: one checkout per repository, shared by every analysis. `load_persisted_analysis_command` (`:640-658`) fetches and runs `git checkout <commit_sha>` in it, and the pipeline then reads files from that directory (parser, test discovery, assertions, tamper). There is no lock in the worker or in `local_git.py` (no flock/lock code in either).
- Scenario: two replicas take PR 1 and PR 2 of one repository. Worker 1 checks out sha1; worker 2 checks out sha2 while worker 1 is parsing. Worker 1 then builds the graph and selects tests from PR 2's tree and stores/publishes the result under PR 1's analysis. The diff provider uses the shared object store (fine) but the file readers do not. Concurrent `fetch`/`checkout` also collide on `index.lock`, giving spurious failures that burn attempts (C-05). C-02 produces the same overlap with a single repository on two replicas.
- Fix: per-analysis `git worktree add --detach <path> <sha>` (removed at the end), or a per-repository file lock around fetch+checkout+analysis.

### C-04 (medium, reading): one transaction for the whole job

- `_run_claimed_job` opens one session at `runner.py:233` and commits only at `:308`, after clone, graph build, tests, mutation, v2 and publication. `mark_running` and `complete_analysis` only `flush` (`sqlalchemy_store.py:113-138`).
- Effects: (1) "running" is never visible: during the whole run the API and dashboard see `pending`; (2) on PostgreSQL the transaction holds the `analyses` row lock; a reaper in another replica that decides to fail the same row after `analysis_deadline_seconds` (`reap_stuck_analyses`, `sqlalchemy_job_queue.py:262-324`) blocks on that lock with no lock timeout and stalls its own loop, and when the first job then commits COMPLETED the reaper's already-loaded object writes FAILED over it and publishes a failure; (3) the GitHub result is published (`runner.py:301`) before `queue.complete` and the commit (`:307-308`), so a failed commit retries the job and publishes again; (4) a connection idle in transaction for up to hours is exposed to server `idle_in_transaction_session_timeout`.
- Fix: commit status transitions (`running`, `completed`) in their own short transactions, keep only artefact writes together, publish after the commit that records completion.

### C-05 (medium, reading): retries are immediate

- `requeue` (`sqlalchemy_job_queue.py:224-239`) puts the job back to PENDING with no earliest-start time. `claim_next` orders by `created_at` (`:127`), so the same job is next; the loop waits only `poll_interval_seconds` (2 s, `runner.py:450`).
- Scenario: a 30-second GitHub outage, a DNS blip or an expired installation token in flight makes clone/token fail three times in about six seconds. The final attempt fails the analysis, and the poller deliberately never retries failed head commits (`retry_failed=False`, `poller.py:268-271`), so the PR stays failed until someone re-runs it.
- Fix: add `not_before` with exponential backoff and jitter, filtered in `claim_next`; treat clearly permanent errors (validation, not found) as non-retryable.

### C-06 (medium, reading): no timeouts on git

- `LocalGitRepositoryClient._run` (`local_git.py:118-125`) calls `subprocess.run` without `timeout`; so does `_origin_remote_url` (`:133-139`). A stalled remote or a negotiation that never ends blocks the worker indefinitely. After 30 minutes C-02 lets another replica start the same job while the first process still holds the repository (C-03) and an installation token.
- Fix: `timeout=` (configurable, for example 600 s), kill the process group on expiry, report as retryable; set `http.lowSpeedLimit/lowSpeedTime`.

### C-07 (medium, reading): the cache grows forever and a dirty tree can wedge a repository

- Nothing prunes `REPOSITORY_CACHE_DIR` (`rmtree` appears only for sandbox and mutation temp dirs). Each repository is cloned in full once, then `git fetch --all --prune` (`local_git.py:30-34`) and `fetch origin +refs/pull/<n>/head` (`:66-75`) add objects forever: no `git gc`, no size cap, no per-org quota. A tenant connecting many or large repositories fills the `radius-repository-cache` volume; RUNBOOK.md:116-133 offers only manual removal. A full disk fails jobs for every tenant.
- `checkout` (`:52`) is plain `git checkout <sha>`: no `--detach`, `--force` or `git clean`. Untracked leftovers from a previous run (generated files; test output when tests run in-process) can make it fail with "untracked working tree files would be overwritten", and a worker killed mid-checkout (C-09) leaves `.git/index.lock`; every later job for that repository then fails until an operator removes it.
- Fix: `git checkout --detach -f <sha>` and `git clean -ffdx` per job (or a fresh worktree, see C-03), age/size-based pruning of idle repositories, periodic `git gc --auto`.

### C-08 (low, confirmed): the cache path can leave the cache directory

- `_safe_path_segment` (`runner.py:716-719`) keeps `.`; owner and name come from the API (`POST /repositories` takes free-form `owner` and `name`, `schemas/repositories.py:13-14`). Repro (path arithmetic): owner `..`, name `etc`, id 5 gives `/var/lib/radius/repositories/../etc-5`. The worker clones into (or fetches in) that sibling path, created with `mkdir(parents=True)` (`local_git.py:37`). The impact is limited to one level and a `<name>-<id>` suffix, but it is a path escape.
- Fix: reject empty/`.`/`..` after sanitising, or derive the directory from the repository UUID only (also removes owner/name collisions between tenants).

### C-09 (medium, reading): shutdown and supervision gaps

- `run_worker` installs SIGTERM/SIGINT handlers that finish the current job (`runner.py:116-128`), and docs/operations/LIVE_GITHUB_DEMO.md:208 and UPGRADE.md:31 rely on it. Compose sets no `stop_grace_period`, so `docker compose stop worker` (the documented "drain") sends SIGTERM and SIGKILL after 10 s. Any real job is killed mid-run, stays RUNNING for `WORKER_JOB_STALE_AFTER_SECONDS`, consumes an attempt and leaves an "in progress" check run until the reaper completes it. The same SIGKILL can leave `.git/index.lock` (C-07).
- `docker-compose.yml` has no `restart:` policy for `postgres`, `api`, `worker`, `dashboard` (only the two one-shot services have `restart: "no"`), so a crash or OOM kill leaves the worker dead without notice. The worker healthcheck (`apps/worker/Dockerfile:79-80`) only opens a DB connection, so a wedged loop (C-06) still reports healthy.
- Fix: `stop_grace_period` of at least `WORKER_TEST_TIMEOUT_SECONDS` plus margin, `restart: unless-stopped`, and a last-iteration timestamp checked by the healthcheck.

### C-10 (low, reading): Compose drops documented worker settings

- The worker `environment:` block (`docker-compose.yml:118-153`) does not forward `RADIUS_RETENTION_DAYS`, `RADIUS_RETENTION_DRY_RUN`, `RADIUS_FEATURE_MUTATION` and `RADIUS_MUTATION_*`, `RADIUS_INTENT_EXTRACTION_MODE`, `RADIUS_FEATURE_SUGGEST_TESTS`, `WORKER_ANALYSIS_DEADLINE_SECONDS`, `WORKER_REAPER_INTERVAL_SECONDS` (grep count 0 each; `WORKER_TEST_EXECUTION_MODE` appears only in a header comment, line 7). An operator following docs/operations/CONFIGURATION.md:89 (retention is a "worker" setting) sets it in `.env`, nothing happens and the database grows. A-09 lists the missing API pepper; this is the worker counterpart.
- Fix: forward them (or use `env_file`) and let `scripts/check_compose.py` fail when a documented worker/API setting is not forwarded.

### C-11 (medium, reading): unbounded and N+1 list endpoints

- `GET /analyses` without `repositoryId` (`routes/analyses.py:98-140`) lists every repository of the org, then per repository calls `get_repository` (1 query) and `list_analyses` (`sqlalchemy_store.py:58-83`: the analyses query plus `selectinload` of `changed_files` and `blast_radius`, `:205-209`, so 3 queries) with no `LIMIT` and no pagination. Cost grows with repositories x analyses x changed files, on the dashboard's main list. `GET /repositories/{id}/pull-requests` (`routes/repositories.py:202-216`) and `GET /repositories` are unbounded too; only intent history (`intent.py:172`) and test executions (`tests.py:342`) take `limit`.
- Fix: add `limit/cursor` to `AnalysisStore.list`, query once with `repository_id IN (...)`, return counts instead of loading all changed files for list views.

### C-12 (medium, reading): duplicate analyses are not prevented by the schema

- `Analysis` (`models.py:211-268`) has indexes but no unique key on (`pull_request_id`, `commit_sha`), not even a partial one for active statuses. `start_analysis` (`services.py:68-76`) calls `find_active` and then inserts (`sqlalchemy_store.py:37-56`): check-then-insert. Webhook redelivery (A-11 notes the delivery id is recorded after processing), the poller (`poller.py:248-275`; every replica polls independently) and `sync-pull-requests` can all pass the check together and create two analyses and two jobs for one head commit. Each runs the full pipeline and publishes (a second check-run update and possibly a second PR comment, compare B-16).
- Related to A-05: `Repository.github_repository_id` is globally `unique=True` (`models.py:111-115`), not unique per organization; that is what makes the squatting in A-05 permanent for the first registrant.
- Fix: partial unique index on (`pull_request_id`, `commit_sha`) where status in (pending, running); catch `IntegrityError` and return the existing row.

### C-13 (medium, reading): auth tables are outside the migration history

- `radius_api/main.py:104-107` runs `DomainBase.metadata.create_all` and `AuthBase.metadata.create_all(bind=auth_engine)` at API start; Alembic's `env.py:5` imports only `radius_shared.database` models, so `auth_users`, `auth_accounts`, `auth_tokens`, `auth_oauth_flows`, `auth_sessions` are in no revision (docs/security/SSO_DESIGN.md:19 admits it; docs/operations/UPGRADE.md:17 says "Alembic stays the authority for schema changes").
- On a database built through migrations only, the tables appear when the API first starts, so sign-in works. But: (a) `create_all` never alters existing tables, so any later column or index added to an auth model silently never reaches an existing database and breaks sign-in at runtime after upgrade (a brand-new table such as `auth_oauth_flows` is the only change this mechanism can ship); (b) `alembic check`/autogenerate cannot see drift; (c) a runtime DB role without DDL rights makes the API fail at start; (d) no downgrade or restore story covers them; (e) nothing purges `auth_sessions` and `auth_tokens` (only expired `auth_oauth_flows` are deleted, `oauth.py:179`), so they grow without bound.
- `auth_users.organization_id` is a `String(36)` with no foreign key to `organizations.id`; the auth user and the domain `users` row are tied only by e-mail and a copied UUID, and `provision_domain_user_and_org` runs `create_all` inside request handling with the exception swallowed (`auth.py:146-151`).
- Fix: put the auth models into the Alembic metadata with a baseline revision (create-if-missing for existing installs), remove `create_all` from lifespan and request paths, add retention for sessions and tokens.

### C-14 (medium, confirmed): the auth engine bypasses the URL normaliser

- `apps/api/src/app/database.py:8` calls `create_engine(settings.database_url, ...)` directly; `database_url` is read from `DATABASE_URL` (`app/config.py:19`). Everything else goes through `normalize_database_url` (`radius_shared/database/session.py:22-28`) or Alembic's `get_database_url`, which rewrite `postgres://` to `postgresql+psycopg://`. Repro: `create_engine("postgres://u:p@h/db")` raises `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`, and this runs at import of `app.database`. With the common managed-database form `postgres://` the API never starts although migrations and the worker work. The auth engine also lacks `pool_pre_ping=True` (stale connections after a DB restart give 500s on sign-in until recycled) and is a second connection pool beside the domain engine in the same process.
- Fix: build the auth engine with `create_database_engine`/`normalize_database_url` and share one engine for both metadata sets.

### C-15 (low, confirmed): nullability drift on `users.github_user_id`

- Repro: `alembic upgrade head` on SQLite followed by `alembic.autogenerate.compare_metadata` against the `radius_shared.database` metadata reports exactly one difference: `modify_nullable users.github_user_id (DB NOT NULL, model nullable)`. The model (`models.py:85-89`) says `int | None`; migration 0001 (`:91`) created it NOT NULL. Code that trusts the model and inserts NULL fails on every migrated database. Today it is masked because `provision_domain_user_and_org` (`apps/api/src/app/auth.py:172-178`) fabricates a 60-bit number from `sha256(email)` for password users and stores it as a GitHub id, so the column is not trustworthy for any lookup by GitHub id.
- Everything else matched. Comparison is limited by SQLite's weak type reflection; PostgreSQL enum value sets (`analysisstatus`, `analysisjobstatus`, `repositorystatus`) were compared by reading and agree with `enums.py`.
- Fix: a data-preserving migration making it nullable, and store NULL for password users.

### C-16 (low, reading): release publish gating is tight but has gaps

- The `publish` job (`release.yml:140-215`) is gated on tag push, not dry run, `vars.RADIUS_RELEASE_PUBLISH == 'true'` and a digest-pinned cosign image. It does not fire unintentionally: `workflow_dispatch` cannot publish and an unset variable skips it. Gaps: no `environment:` (no required reviewer), so anyone who can push a `v*` tag, from any branch (nothing checks the tag points into `main`), triggers a signed push once the variable is on; the pushed image is a second `docker buildx build` (`:198-205`), not the image the `build` job scanned and SBOM'd, and the pushed digest is not rescanned; the `:<version>` tag is mutable.
- Fix: protected `environment` for `publish`, `git merge-base --is-ancestor $GITHUB_SHA origin/main`, build once, scan the pushed digest, then sign.

### C-17 (low, reading): migrations race on multi-replica start

- `apps/api/Dockerfile` CMD runs `python -m alembic upgrade head && uvicorn ...` in every container; Compose also has a one-shot `migrations` service (`docker-compose.yml:36-44`). Alembic takes no database lock on PostgreSQL, so two API replicas starting together can both apply a revision; one fails with "already exists" and, with no restart policy (C-09), stays down.
- Fix: run migrations in one job only, or wrap the upgrade in `pg_advisory_lock` in `env.py`.

### C-18 (low, reading): worker settings have no sanity bounds

- `config.py:25-37`: `job_stale_after_seconds`, `job_max_attempts`, `analysis_deadline_seconds`, `poll_interval_seconds` are plain numbers. `WORKER_JOB_MAX_ATTEMPTS=0` makes `claim_next` (`attempts < 0`) never match, so the queue stops silently and the reaper fails everything after the deadline; `WORKER_JOB_STALE_AFTER_SECONDS<=0` makes every running job immediately reclaimable (C-02 even with one replica running two loops); the field description says the deadline must exceed `stale * attempts` but nothing enforces it (defaults 7200 against 5400), and the reaper measures from `analysis.started_at` which is the creation time (`sqlalchemy_job_queue.py:293`), so a queue backlog of two hours fails analyses that never ran.
- Fix: `Field(ge=1)` bounds plus a validator for the deadline relation; measure the deadline from claim time.

### C-19 (low, reading): documentation that contradicts the code

- `docs/KNOWN_LIMITATIONS.md:31`: "**No SSO/OIDC.** Password sign-in with e-mail verification only." Code: Google and GitHub OAuth/OIDC exist (`apps/api/src/app/oauth.py`, `routes_auth.py:374-479`, docs/security/SSO_DESIGN.md). Same in `docs/operations/HARDENING.md:130` ("No SSO/RBAC (backlog), no audit log"; API-key and intent audit rows exist).
- `docs/KNOWN_LIMITATIONS.md:33`: "**No DAST** and no external penetration test." Code: `.github/workflows/dast.yml` runs ZAP baseline against API and dashboard. Line 32: "No signed releases, images or SBOM. Nothing is published": `release.yml` generates SBOMs and, when opted in, publishes and cosign-signs; the default state matches, the capability exists.
- `docs/operations/RUNBOOK.md:87-88`: "The GitHub client ... has **no specific rate-limit handling** (no `Retry-After` / `x-ratelimit-*` logic was found in it)." Code: `packages/github/src/radius_github/client.py` raises `GitHubRateLimitError` after bounded retries (line ~553) and the poller backs off per installation (`poller.py:151-165`).
- `docs/operations/UPGRADE.md:31-32`: "stop the worker (`docker compose stop worker`) so no job is mid-flight. Running jobs are leased in the database". Code: there is no lease renewal (C-02) and Compose kills the worker after 10 s (C-09), so stopping always leaves a mid-flight job.

### C-20 (low, suspected): host-only session cookie

- `_set_session_cookie` (`routes_auth.py:102-110`) sets no `domain`. The dashboard middleware reads `radius_session` on its own host (`middleware.ts:28`) while the browser sends sign-in requests to `NEXT_PUBLIC_API_URL` (`lib/auth.ts:3`). This works on `localhost:3000`/`localhost:8000` (cookies ignore ports) and behind one reverse-proxy origin. With `app.example.com` and `api.example.com` the cookie is bound to the API host, the dashboard never sees it and redirects to `/login` forever. Not exercised; I did not find a statement of the supported topology.
- Fix: document the same-origin requirement or add a configurable cookie domain.

### C-21 (low, reading): default credentials and bind addresses

- `docker-compose.yml` hard-codes `POSTGRES_PASSWORD: radius` (`:23`) and `DATABASE_URL: postgresql+psycopg://radius:radius@postgres:5432/radius` (`:42`, `:61`, `:121`), not read from `.env`; changing the password means editing the file. Postgres is published on loopback only, so the exposure is other containers or local users. `api` (`:96`) and `dashboard` (`:174`) publish on all interfaces; with C-01 the dashboard port is the weakest door.
- Fix: `${POSTGRES_PASSWORD:?}` generated by `gen_dev_env.py`; bind `127.0.0.1:` by default.

## Areas reviewed and found sound

- **Retention task** (`maintenance.py`): fixed table allowlist built from model objects (no string SQL), `id IN (batch)` deletes with a commit per bounded batch, dry run only counts, minimum 7 days, `OUTBOX_MAX_ATTEMPTS=5` equals the outbox `MAX_ATTEMPTS` so live rows are not deleted, dialect-neutral; unparseable values turn it off.
- **Job claiming on PostgreSQL**: `FOR UPDATE SKIP LOCKED` on the single selected row, committed right after the claim; `cancel_queued` is one conditional UPDATE; enqueue is idempotent per analysis (unique `analysis_jobs.analysis_id`).
- **Failure recording**: the rolled-back pipeline session is replaced by a fresh one for job/analysis failure; the final attempt fails the analysis and completes the GitHub check; the reaper completes checks for exhausted jobs; errors are redacted before storage and logging.
- **Poller**: bounded per tick (analyses and repositories), rotating cursor, per-installation rate-limit backoff, one repository's failure isolated, jitter; `retry_failed=False` avoids retry storms.
- **Migrations**: all 16 revisions form a linear chain and upgrade cleanly end to end (run on SQLite); model-versus-migration comparison shows a single drift (C-15); downgrades drop their own objects and enum types; the only data-destructive downgrade (0005, duplicate paths) says so; batch mode is used where SQLite needs it. Frequently filtered columns (`analyses.repository_id/pull_request_id/commit_sha`, jobs `status,created_at`, the idempotency unique key, outbox `available_at`) are indexed.
- **Dashboard proxy mechanics** (`lib/proxy.ts`): anchored allowlist with per-route methods; segment checks reject `.`, `..`, `/`, `%`, NUL (a decoded `%2e%2e` or double-encoded form is rejected); upstream URL built only from the configured base; `redirect: "error"`; header allowlist built from scratch (no cookie, Authorization or Host forwarded; `If-Match` and idempotency key validated); 5 MiB body cap, 30 s timeout; upstream error detail is not leaked. No `dangerouslySetInnerHTML`/`innerHTML` in `app/`, `components/`, `lib/`; only `NEXT_PUBLIC_RADIUS_API_BASE_URL`, `..._ORGANIZATION_ID`, `..._API_URL` are inlined (no secret). CSP: per-request nonce with `strict-dynamic`, no `unsafe-eval` outside dev, `frame-ancestors 'none'`, `object-src 'none'`, plus nosniff, COOP/CORP, Permissions-Policy and optional HSTS; Next is `^15.5.28`, past the middleware-bypass advisory.
- **CI/CD**: every `uses:` is pinned to a 40-hex SHA (grep; also `scripts/ci/check_action_pins.py`); default `permissions: contents: read` with per-job elevation only for SARIF, GHCR and OIDC; no `pull_request_target` or `workflow_run`; untrusted PR text (title, refs) reaches `commit_lint.py` only via `env:`; the composite action passes inputs through `env:`; no secrets in fork-reachable jobs; stack/dast jobs use generated random local secrets; artifacts contain reports and logs only; the `release.yml` default path publishes nothing and `workflow_dispatch` cannot publish; `scripts/ci/*.py` and `radius_ci.py` use argv lists, no `shell=True`.
- **Containers**: all three images run as uid 10001, base images pinned by digest, `.dockerignore` excludes `.env*`, only public `NEXT_PUBLIC_*` build args, `docker.sock` is not mounted by Compose (the worker image ships only the Docker CLI in the opt-in `sandbox` target), Postgres is published on loopback.
- **API session handling**: one request-scoped session with depth counting, commit on success, rollback and close in `finally` (`dependencies.py:305-335`); the worker uses `with session_factory()` consistently; `pool_pre_ping` on the domain engine; `expire_on_commit=False`/`autoflush=False` set deliberately.

## Not reviewed

- No end-to-end run of the worker, API or dashboard and no PostgreSQL: lock behaviour (C-02, C-03, C-04) is by reading. Migrations were run on SQLite only, so PostgreSQL-specific DDL (enum creation, identifier length from the naming convention, `batch_alter_table` constraint names) is unverified beyond reading.
- Worker internals not read in depth: `intent_ingestion.py`, `execution_mode.py` beyond the environment guard, `radius_worker/verdict_v2/*` (review B), the sandbox runner (review A), `scripts/*.py` helpers other than `scripts/ci/*` and `radius_ci.py`.
- Dashboard components (`data-panels.tsx`, 2800+ lines) were grepped for sinks and navigation, not read; the Playwright e2e suite and `smoke.yml`, `nightly.yml`, `coverage.yml`, `container-scan.yml` were skimmed, not audited line by line; `.zap/rules.tsv` and `.trivyignore` were not checked for over-broad suppressions.
- Not checked: GitHub repository settings (branch and tag protection, environment secrets), the Next.js build output, real cookie behaviour across hosts (C-20 is suspected).
