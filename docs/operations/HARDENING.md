# Hardening checklist

Work through this before exposing Radius to anything but a laptop. Each item says where the behavior is
documented or implemented. Radius is pre-1.0: no external penetration test of the sandbox or the API has been
done (README, security notes), so treat this list as reducing risk, not as a certification.

Legend: **Required** items are needed for a safe deployment; **Recommended** ones reduce risk further.

## 1. Run in production mode

- [ ] **Required.** `RADIUS_ENV=production` on api and worker (Compose already sets it). It tightens CORS validation
  (no `*`, https only) and ignores demo seeding. `RADIUS_ALLOW_INSECURE_DEV` must be unset: it is honoured only in
  `development`/`test` and exists solely to skip API keys and webhook signatures.
- [ ] **Required.** `RADIUS_SEED_DEMO_DATA` unset or `false` (the demo login has a public password).
- [ ] Recommended. Unset `DEV_AUTO_VERIFY_EMAIL`; configure `SMTP_*` so sign-in accounts are verified by mail.

## 2. Secrets

- [ ] **Required.** Generate real values for `API_KEYS`, `RADIUS_API_KEY`, `GITHUB_WEBHOOK_SECRET`,
  `SESSION_SECRET` (32+ chars; the code default and the `.env.example` value are public placeholders) and the
  PostgreSQL password. The reference in [CONFIGURATION.md](CONFIGURATION.md) marks which variables are secrets.
- [ ] **Required.** `RADIUS_API_KEY` and every secret stays server-side. Never use a `NEXT_PUBLIC_` prefix for a
  secret; the dashboard proxy attaches the key server-side so the browser never holds it (F-05).
- [ ] **Required.** Keep `.env` out of version control and images (`.dockerignore` excludes `.env*`; images carry
  no `ENV`/`ARG` secrets, [security/CONTAINERS.md](../security/CONTAINERS.md)). Prefer your orchestrator's secret
  store over a file. The GitHub App private key is a PEM in `GITHUB_APP_PRIVATE_KEY`; scope the App to the
  repositories it needs.
- [ ] Recommended. Rotate by changing the value and restarting the service. Rotating `API_KEYS` requires updating
  `RADIUS_API_KEY` for the dashboard at the same time. Per-key scopes and an audited rotation flow do not exist
  yet (task IT-09).
- [ ] Recommended. Change the default `radius/radius` database credentials in `docker-compose.yml` and do not publish
  port 5432 (`POSTGRES_HOST_PORT`) beyond localhost; the compose file publishes it on all interfaces.

## 3. API authentication and tenancy

- [ ] **Required.** `API_KEYS` holds one `org_id:key` pair per organization. Without keys the API fails closed (403).
  Every request needs `X-Radius-Organization-Id` and the matching `X-Radius-API-Key`.
- [ ] **Required.** Single-tenant only: `GITHUB_SINGLE_TENANT=true` is safe only when exactly one organization uses
  the GitHub App. Leave it `false` otherwise; unknown installations are then rejected with 403.
- [ ] Recommended. Tenant isolation is by organization id in queries and 404 on cross-tenant intent access; a
  dedicated isolation test suite (QS-04) is not done.

## 4. TLS termination and the reverse proxy

Radius does not terminate TLS. Put a proxy (nginx, Caddy, Envoy, a cloud load balancer) in front of the API and the
dashboard.

- [ ] **Required.** HTTPS for the API (GitHub webhooks need a public HTTPS URL) and for the dashboard.
- [ ] **Required.** After TLS works: `RADIUS_HSTS_ENABLED=true` (API and dashboard) and `SESSION_COOKIE_SECURE=true`.
  Never enable HSTS over plain HTTP.
- [ ] **Required.** `RADIUS_TRUSTED_PROXIES` = the IPs/CIDRs of your proxies only. Without it every client appears
  as the proxy IP and shares one rate-limit bucket; with a wrong, broad value clients can spoof `X-Forwarded-For`.
- [ ] **Required.** Proxy timeouts: the app does not defend against slow clients. Set header/body read timeouts
  and consider uvicorn `--timeout-keep-alive` and `--limit-concurrency`
  ([HTTP_HARDENING.md](../security/HTTP_HARDENING.md), body limits section).
- [ ] Recommended. Have the proxy forward only `/api/v1/` (and `/metrics` only to your scraper), and block or
  authenticate `/docs` and `/redoc` (open in production; listed as a follow-up in HTTP_HARDENING.md).
- [ ] Recommended. Rate limits are in memory per replica; with N replicas the effective limit is up to N times the
  setting. Also rate limit at the proxy.

## 5. CORS and browser origins

- [ ] **Required.** `CORS_ORIGINS` = the exact `https://` origin(s) of your dashboard. In production `*`, wildcards and
  `http://` origins stop the API from starting. Localhost origins are added only outside production.
- [ ] Set `FRONTEND_ORIGIN` (sign-in links and OAuth redirects) and `NEXT_PUBLIC_RADIUS_API_BASE_URL` to the public
  URLs, which also feed the dashboard CSP `connect-src`.
- [ ] Keep `RADIUS_CORS_ALLOW_CREDENTIALS=true` only while the dashboard uses cookie sessions (default).

## 6. HTTP limits

- [ ] Defaults are sane: body caps `RADIUS_MAX_BODY_BYTES` 1 MiB, webhook 25 MiB, test-report upload 20 MiB;
  rate limits auth 10/60, webhook 600/60, general 600/60, expensive 20/60
  ([HTTP_HARDENING.md](../security/HTTP_HARDENING.md)). The dashboard proxy uses one server-side key from one IP,
  so all dashboard users share the `general`/`expensive` buckets: raise `RADIUS_RATE_LIMIT_GENERAL` for your
  user count.
- [ ] Recommended. Scrape `radius_http_rate_limited_total{bucket}` (needs `RADIUS_METRICS_ENABLED=true`).

## 7. Test execution isolation

- [ ] **Required.** Keep `WORKER_TEST_EXECUTION_MODE=disabled` (the default) unless you have read
  [EXECUTION_ISOLATION.md](../security/EXECUTION_ISOLATION.md). Run the selected tests in your own CI and upload
  JUnit/JSON instead; the worker process holds database and GitHub App credentials and pull-request code is
  untrusted.
- [ ] **Required.** Never use `unsafe_in_process` outside local development. The worker refuses to start with it in
  `uat`/`production` unless `RADIUS_ALLOW_UNSAFE_EXECUTION=true`; do not set that.
- [ ] If you enable `sandbox`: pre-pulled, pinned image (`WORKER_SANDBOX_IMAGE`, never fetched at analysis time),
  no network in the sandbox, resource limits left at or below the defaults, and the worker running on a host that is
  itself isolated and holds no credentials beyond what it needs. The worker fails closed at startup if the runtime,
  daemon or image is unusable. The container runtime socket is a powerful privilege; gVisor or Firecracker is the
  documented recommendation for production, and no pen test exists.

## 8. Containers and host

- [ ] The images run as uid/gid `10001`, with pinned base images and no compiler. They also ran healthy with a read-only
  root filesystem plus `--cap-drop ALL --security-opt no-new-privileges` (checked in PRD-08); apply those in your
  orchestrator because `docker-compose.yml` does not set them.
- [ ] Worker repository cache volume owned by `10001:10001`; the worker needs `/tmp` as tmpfs on a read-only root.
- [ ] Recommended. Run the container image scan (`.github/workflows/container-scan.yml`) on your own builds.

## 9. LLM and third-party egress

- [ ] **Required.** Leave `GEMINI_API_KEY` unset. The legacy Gemini `SemanticPruner` sends caller source code and
  diffs to Google and is not covered by the LLM egress policy (DEC-021). It now also needs
  `RADIUS_FEATURE_GEMINI_PRUNER=true`, and is not called by the live analysis pipeline.
- [ ] LLM intent extraction is off by default (`RADIUS_LLM_INTENT_ENABLED=false`). When on it sends redacted intent text
  (PR title/body, issues, commit messages), never repository code, to Anthropic for the organizations listed in
  `RADIUS_LLM_INTENT_ORGS`; bound spend with the token caps. Check your provider's retention terms first.
- [ ] The LK-02 link re-ranker (`RADIUS_LLM_LINK_RERANK_*`) would send criterion text, file paths and symbol names;
  it is a library with no caller in the API or worker today.
- [ ] Telemetry: tracing and metrics are off by default and export only to the endpoint you set.

## 10. Intent ingestion and GitHub permissions

- [ ] Grant the GitHub App the minimum in [DEPLOYMENT.md](../DEPLOYMENT.md) section 4. `issues: read` is needed only
  for linked-issue ingestion.
- [ ] `RADIUS_INTENT_ALLOW_CROSS_REPO` stays `false`: the installation token can read every repository of the
  installation, so honoring a PR author's cross-repo link would expose that repository's issue text.
- [ ] Untrusted intent text is sanitised before storage and never executed
  ([PROMPT_INJECTION.md](../security/PROMPT_INJECTION.md)).

## 11. Data

- [ ] Backups taken, encrypted, restore tested ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)).
- [ ] PostgreSQL not reachable from outside the private network; TLS between the services and a managed database
  if it is remote (`?sslmode=require` in `DATABASE_URL`; **Unverified** with this stack).
- [ ] `STORAGE_BACKEND=sql` (memory mode loses everything on restart).

## Not covered

No SSO/RBAC (backlog), no audit log, no CSRF defences beyond cookie flags (PRD-26), no formal tenant isolation or
sandbox penetration test, no published image provenance or signing. See `docs/production-readiness/BACKLOG.md`.
