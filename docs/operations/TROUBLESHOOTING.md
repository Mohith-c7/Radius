# Troubleshooting

Install-time and first-run problems. For a running system see [RUNBOOK.md](RUNBOOK.md). Entries derived from reading
the code and not reproduced on a live stack say **Unverified**.

## The stack does not start

| Symptom | Cause | Fix |
|---|---|---|
| `make: command not found` (Windows) | GNU make is not installed | `.\scripts\dev.ps1 dev`, or `winget install ezwinports.make`, or WSL/Git Bash |
| `port is already allocated` on 5432 | A local PostgreSQL uses it | Set `POSTGRES_HOST_PORT=5433` in `.env`. For 3000/8000 stop the other process (the host ports are fixed in `docker-compose.yml`) |
| `docker compose` build is very slow or runs out of memory | Cold build of three images | First build takes several minutes by design; give Docker more memory. Sizing: **Unverified** |
| `migrations` exits non-zero | Database not ready or bad `DATABASE_URL` | `docker compose logs migrations postgres`. Inside Compose the host is `postgres`, not `localhost` |
| `api` unhealthy | `/api/v1/ready` fails (database or queue) | `docker compose logs api`; `curl -si localhost:8000/api/v1/ready` returns 503 `not_ready` and the log has the exception |
| `api` exits at start with a validation error about CORS | Production mode rejects `*`, wildcard hosts and `http://` origins in `CORS_ORIGINS` | Use exact `https://` origins ([HARDENING.md](HARDENING.md)) |
| `api` exits: `SESSION_SECRET` ... at least 32 characters | The sign-in settings require a 32+ character secret | Set a longer `SESSION_SECRET` |
| Worker permission errors on `/var/lib/radius/repositories` | Volume created by an older root-owned image | `docker compose down`, remove the `radius-repository-cache` volume (it is a rebuildable cache) or `chown -R 10001:10001` it |
| Worker exits immediately in sandbox mode | The sandbox must prove itself usable at startup | See the sandbox table in [RUNBOOK.md](RUNBOOK.md); the Compose worker has no container runtime |

## The UI or API rejects me

| Symptom | Cause | Fix |
|---|---|---|
| API calls return 403 `ACCESS_DENIED` "Radius API keys are not configured" | Compose runs in production mode and `API_KEYS` is empty | Set `API_KEYS=<org uuid>:<key>`, `RADIUS_API_KEY=<key>` and a matching `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID` ([INSTALL.md](INSTALL.md)); restart api and dashboard |
| 403 "Invalid Radius API key for organization" | Key or organization id mismatch | The pair in `API_KEYS` must match `X-Radius-API-Key` and `X-Radius-Organization-Id`; for the dashboard, `RADIUS_API_KEY` and the org id |
| Dashboard says to set `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID` | Variable empty | Set it and rebuild the dashboard image (`NEXT_PUBLIC_*` are normally inlined at build time, **Unverified** here) |
| Dashboard panels empty, browser calls go to `localhost:8000` from a remote machine | `NEXT_PUBLIC_RADIUS_API_BASE_URL` still the default | Set it to the public API URL and rebuild |
| Sign-up works but I cannot log in | Account not verified: auto-verify applies only when `RADIUS_ENV=development` or `DEV_AUTO_VERIFY_EMAIL=true` | For local evaluation set `DEV_AUTO_VERIFY_EMAIL=true`; for real use configure `SMTP_*` |
| Sign-in requests blocked by the browser (CORS) on `http://localhost:3000` | In production mode localhost origins are not added to the allow-list and `http://` origins are rejected by validation (`apps/api/src/radius_api/middleware/hardening.py`, `config.py`). **Unverified in a browser** | Serve dashboard and API over HTTPS behind a proxy and list the dashboard in `CORS_ORIGINS`, or use `make dev-local` (development mode, native processes) for local work |
| 429 `Too Many Requests` | Rate limit (auth is 10 per 60 s per client IP; the dashboard shares one bucket) | Wait for `Retry-After`; tune `RADIUS_RATE_LIMIT_*`; set `RADIUS_TRUSTED_PROXIES` behind a proxy |
| 413 / 415 | Body over the cap, or a non-JSON body on a JSON route | Caps in [CONFIGURATION.md](CONFIGURATION.md); test reports go to the upload route as raw XML/JSON |

## GitHub does not talk to Radius

| Symptom | Cause | Fix |
|---|---|---|
| Nothing happens on a pull request | Webhook not delivered or ignored | GitHub App, Advanced, Recent Deliveries; see the webhook table in [RUNBOOK.md](RUNBOOK.md) |
| 403 on every delivery | Secret mismatch, or the installation is not linked | Same secret on both sides; single org: `GITHUB_SINGLE_TENANT=true` + `GITHUB_DEFAULT_ORGANIZATION_ID` |
| Analysis runs but no check run or comment | Publishing disabled or credentials only on the API | `GITHUB_PUBLISH_RESULTS=true`, and `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` on the **worker** (Compose forwards them to the worker) |
| Private key rejected | PEM newlines lost in `.env` | Write the key on one line with `\n` escapes (DEPLOYMENT.md); verify by the worker log on the first token request |
| Intent panel stays empty | `RADIUS_FEATURE_INTENT_INGESTION` is off by default | Set `true` on **both** api and worker, give the App `issues: read` for linked issues ([github-app-validation/RUNBOOK.md](../github-app-validation/RUNBOOK.md)) |

## The verdict is not what I expected

| Symptom | Cause |
|---|---|
| `insufficient_evidence`, "Selected tests were not executed; upload CI results to verify" | Normal on a default install: in-worker test execution is `disabled`. Upload JUnit/JSON from your CI, bound to the head SHA ([CI_INTEGRATION_GUIDE.md](../CI_INTEGRATION_GUIDE.md)) |
| Still `insufficient_evidence` after upload | Results must cover the selected tests, match the analysed head SHA and not be all skipped (`scoring.py` gaps list the reason). The PR comment and check run are not re-published after a later upload |
| `insufficient_evidence` with "N flaky test(s) ... excluded from verification evidence" | Flaky handling is on: `WORKER_TEST_RERUNS` above 0 (default 0) with sandbox mode found a test that failed then passed. With `WORKER_FLAKY_POLICY=exclude` (default) that blocks `verified`; `fail` counts it as a failure ([FLAKY_TESTS.md](../FLAKY_TESTS.md)) |
| `failed` | At least one test failed (stable failure) |
| Score shown as "heuristic" | The 0-100 score is `heuristic_uncalibrated`, not a probability |
| `GET /api/v1/analyses/{id}/verdict-v2` answers 404 `disabled` | `RADIUS_FEATURE_VERDICT_V2` is `off` (default). It is an alpha (set it on api and worker); `shadow` stores v2 and still publishes v1. How to read it: [verdict-v2.md](../verdict-v2.md) |
| Intent, linking, tamper and assertion features have no visible effect | They are off by default, and none of them feeds the v1 verdict. Intent ingestion stores snapshots; symbol changes, tamper rules and assertion extraction only log counts. Their results reach a verdict only through Verdict v2 (`RADIUS_FEATURE_VERDICT_V2`), which recomputes them itself |

## Where to look

```bash
docker compose logs -f --tail 200 api worker dashboard migrations
docker compose exec postgres psql -U radius -d radius
curl -s http://localhost:8000/api/v1/health
```

Turn the log level up with `RADIUS_LOG_LEVEL=DEBUG` (api and worker, restart required). Secrets are redacted in
logs, but still review a log before sharing it ([OBSERVABILITY.md](../OBSERVABILITY.md)). Vulnerabilities:
[SECURITY.md](../../SECURITY.md), not a public issue.
