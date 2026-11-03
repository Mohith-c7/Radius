# Security and auth code review of `origin/develop` (45a9bcf)

Scope: sign-in/sessions/OAuth, tenant isolation across API routes, webhooks, GitHub integration, HTTP hardening, sandbox/untrusted-code execution, secrets handling. Read-only review; every finding was re-read at the cited lines. "Repro" = a small repro I ran; "careful reading" = traced through code; "suspected" = plausible but not traced end to end.

## Summary table

| Id | Severity | Confidence | Location | One line |
|----|----------|-----------|----------|----------|
| A-01 | critical | repro (git side) + reading (path) | packages/repository/src/radius_repository/infrastructure/local_git.py:38-40; apps/api/src/radius_api/schemas/repositories.py:12-16 | Unvalidated `cloneUrl` goes to `git clone <url> <dest>` with no `--`: option injection (`--upload-pack=`) runs commands on the worker |
| A-02 | high | careful reading | local_git.py:179-188 (`_header_scope`, `_git_environment`); apps/worker/src/radius_worker/runner.py:728-742 | GitHub installation token is sent, scoped to whatever host the repo's `clone_url` names; `file://`/local paths also allowed |
| A-03 | high | careful reading | apps/api/src/radius_api/github_pull.py:117-178; routes/repositories.py:219-303 | `connect-github` discovers and stores the installation of ANY repo the App covers; no proof the caller owns it |
| A-04 | high | careful reading | apps/api/src/radius_api/routes/coverage.py:22-119 | Coverage GET/POST routes never check analysis ownership: cross-tenant read and write; the POST org check is a tautology |
| A-05 | high | careful reading | packages/repository/src/radius_repository/application/services.py:40-58; routes/repositories.py:50-104; routes/github_webhooks.py:605-621 | `POST /repositories` returns another org's repo and lets a tenant squat a `github_repository_id`; webhooks then route to the squatter |
| A-06 | medium | careful reading | routes/analyses.py:48-84; schemas/analyses.py:12-14; packages/analysis/.../value_objects.py:12-18 | `pullRequestId` not checked against repo/org; `commitSha` only length-limited (reaches `git checkout` and GitHub URL paths) |
| A-07 | medium | careful reading | apps/api/src/app/routes_auth.py:143-178, 277-295; app/auth.py:110-138, 141-206 | Account pre-hijacking: unverified signup gets a session; password and sessions survive verify/reset; signup joins an existing org by email |
| A-08 | medium | careful reading | app/routes_auth.py:164-175, 252-270, 307-317 | `name` is interpolated unescaped into HTML mail sent to the victim's address |
| A-09 | medium | careful reading + grep | docker-compose.yml:56-92; app/config.py:26-45, 309-326 | Compose never forwards `RADIUS_API_KEY_PEPPER` (managed keys unusable); production profile allows non-secure cookies |
| A-10 | low | careful reading | app/routes_auth.py:122-132 | `current_user` dereferences a missing session row: 500 instead of 401 |
| A-11 | low | repro (compare_digest) + reading | routes/github_webhooks.py:73-91, 726, 690 | Webhook: non-ASCII signature header gives 500; non-int repo id gives 500; up to 25 MiB buffered before auth |
| A-12 | low | careful reading | app/routes_auth.py:181-194, 143-148; middleware/rate_limit.py:226-229 | Login timing/enumeration; auth rate limit is per IP only |
| A-13 | low | repro (urljoin) + reading | radius_api/github_pull.py:53-70; packages/github/.../client.py:420-423 | `owner/name` may be `.`/`..`; `urljoin` normalizes the traversal into other GitHub API paths |
| A-14 | low | careful reading | app/auth.py:110-138 | Single-use action token is check-then-set, not atomic |
| A-15 | low | careful reading | app/routes_auth.py:220-227 | `/refresh` mints a new session per call, never revokes the old one, and is unthrottled |
| A-16 | low | careful reading | app/auth.py:29-47; radius_api/observability.py:61; routes/repositories.py:143 | Dev switches honoured in any env; `/metrics` open; 403 vs 404 existence oracle on ids |
| A-17 | low | careful reading | packages/testing/.../junit_parser.py:140-150; sandbox_runner.py (`_run_once`, results dir chmod 0o777) | Stdlib XML fallback if defusedxml missing; results dir mode 0777 on host; sandbox evidence is author-controlled by design |

---

## Findings

### A-01 (critical) Option injection in `git clone` via `cloneUrl`: command execution on the worker

- `apps/api/src/radius_api/schemas/repositories.py:16` `clone_url: str` has no validation. `routes/repositories.py:82-91` stores it as given (a write-scope key is enough). `ConnectRepositoryCommand`/`Repository` do not validate it either.
- The worker later runs `("git", "clone", clone_url, str(destination))` (`packages/repository/src/radius_repository/infrastructure/local_git.py:38-40`, called from `apps/worker/src/radius_worker/runner.py:640-645`). There is no `--` before the URL.
- Scenario: a tenant with a write key connects a repository (a real `repositoryId`/owner/name the App covers) with `cloneUrl` = `--upload-pack=<shell command>`; any analysis for it (webhook, `sync-pull-requests`, poller) makes the worker clone it. git treats the value as an option and runs the command through a shell.
- Repro (ran locally, same argv shape): `git clone "--upload-pack=echo PWNED > pwn; false" out` created file `pwn` containing `PWNED`. The worker holds `DATABASE_URL` and the GitHub App private key, so this is a full tenant and host escape.
- Fix: validate `clone_url` at the API boundary (https only, host equal to the configured GitHub host, no userinfo, must start with `https://`), preferably derive it from GitHub's metadata instead of accepting it from the caller, and add `--` plus `-c protocol.allow=never -c protocol.https.allow=always` in `clone_or_fetch`. Re-validate in the worker too (rows already stored are untrusted).

### A-02 (high) Installation token sent to an arbitrary host; local-path and `file://` clones

- `local_git.py:179-188` scopes the auth header to the origin of `remote_url` (`http.<scheme>://<host>/.extraHeader`), i.e. to whatever host the stored `clone_url` has. `_github_clone_headers` (`apps/worker/src/radius_worker/runner.py:~728-742`) always supplies the installation token when the App is configured. A repository whose `clone_url` is `https://attacker.example/x.git` therefore receives `Authorization: Basic x-access-token:<installation token>`. The docstring presents the scoping as redirect protection, but the scope follows the attacker-supplied URL. The token belongs to the organization's installation and reads every repository in it.
- git's default protocol policy also allows `file://` and plain paths, so `cloneUrl=/var/lib/radius/cache/<other-owner>/<repo>-<id>` clones another tenant's cached checkout (layout in `runner.py:_repository_cache_path`), which the analysis then processes.
- Fix: same allowlist as A-01; attach the header only when the host equals the configured GitHub host; refuse non-https schemes.

### A-03 (high) `connect-github` binds the caller's org to any installation the App has

- `routes/repositories.py:239-247` calls `open_access(... discover=True)`. `github_pull.py:140-178` asks GitHub `GET /repos/{owner}/{repo}/installation` with the App JWT. That succeeds for every repository of every customer who installed the (shared) App. If the caller's org has no installation, the discovered id is stored on it (`:156-160`); then an installation token is minted (`open_access`, `:206`) and the repo is connected to the caller's org (`routes/repositories.py:283-303`), unless some org already owns the repo.
- Scenario: org B (any write key) submits `victim/private-repo`. B now holds the victim's installation id, can sync/analyze every repo of that installation (the poller and `sync-pull-requests` use the org's installation id), and the worker clones and publishes with the victim's token. Nothing proves the caller controls the GitHub account. 404 vs success also tells any tenant whether a given private repo has the App installed.
- The only guard is "already connected to another organization" (`:265`), which is first come, first served.
- Fix: bind installations to orgs through a proof of control (installation callback / GitHub OAuth with state tied to the org, or admin approval); never persist a discovered installation id for an org that has not been linked that way; enforce uniqueness of `Organization.github_installation_id` and reject discovery results already linked to a different org.

### A-04 (high) Coverage routes lack tenant checks (read and write)

- `routes/coverage.py:76-94` (`GET /coverage/analysis/{id}`) and `:101-119` (`.../report`) take `analysis_id` and only require a valid principal; they never load the analysis/repository or call `ensure_same_organization`. Any org with a read key gets another org's coverage summary/report if it knows the UUID (`analysis_id: str`, not even parsed).
- `ingest_coverage` (`:22-69`) does `ensure_same_organization(principal, UUID(organization_id))` where `organization_id` is the same `X-Radius-Organization-Id` header that already authenticated the principal, so it can never fail. `X-Analysis-Id` is not tied to the org; `_require_analysis` (`packages/confidence/.../coverage_sqlalchemy.py:29`) checks existence only. A ci-upload key of org B can overwrite/poison coverage of org A's analysis, which feeds confidence and verdicts.
- Invalid UUIDs in `X-Analysis-Id`/`X-Radius-Organization-Id` raise `ValueError` (500).
- `/coverage/artifact` and `/coverage/symbol` pass a nil analysis id, so they are dead code rather than a leak.
- Fix: resolve analysis -> repository -> organization as `routes/confidence.py:41-43` does (or the uniform-404 `get_intent_analysis_id`, `routes/intent.py:78-103`) in all three handlers; drop the tautological header check.

### A-05 (high) `POST /repositories` leaks foreign repos and allows squatting a GitHub repository id

- `RepositoryApplicationService.connect_repository` (`packages/repository/.../services.py:40-58`) returns the existing repo for the same `github_repository_id` whatever its organization. The route (`routes/repositories.py:67,82-104`) checks only the org in the request body, then returns the result with no ownership check. A tenant posting a victim's `repositoryId` receives the victim repo's UUID, organization id, clone URL, branch, status.
- Conversely the first caller to register an id owns it with no proof they own the GitHub repo. Webhook routing resolves the tenant by existing repo first (`routes/github_webhooks.py`, `_resolve_webhook_organization_id`), so after squatting, the victim's signed deliveries (PR titles/bodies when intent ingestion is on, analyses) are filed under the squatter's org, and `_record_installation_id` then writes the victim's installation id onto an org that has none (same end state as A-03).
- Fix: in `connect_repository` return a conflict when `existing.organization_id != command.organization_id`; require GitHub-verified ownership (the `connect-github` style with a proper installation binding) instead of caller-asserted ids/URLs.

### A-06 (medium) `POST /analyses`: `pullRequestId` and `commitSha` not validated

- `routes/analyses.py:56-84` checks the repository's org but not that `pull_request_id` belongs to that repository/org, so an analysis of org B's repo can be attached to org A's pull request (the worker reads `PullRequest.target_branch`; the publisher posts to it). `commitSha` is any string up to 40 chars (`schemas/analyses.py:13`, `value_objects.py:16`); only `/analyses/lookup` applies `_COMMIT_SHA` (`:36`). The value reaches `git checkout <sha>` (`local_git.py:57`; option-like values such as `-f`) and GitHub URL paths (`list_check_runs_for_ref`, `client.py:~320`, unquoted; `/` and `..` are collapsed by `urljoin`).
- Fix: validate `^[0-9a-fA-F]{7,40}$`; verify `pull_request.repository_id == repository.id`; use `git checkout --detach <sha>^{commit}` or `--`.

### A-07 (medium) Account pre-hijacking and weak session lifecycle

- `signup` (`app/routes_auth.py:143-178`) creates an account for any email with an attacker-chosen password and immediately sets a session cookie (`:177`) although `email_verified` is false (`login` does not check it either, `:181-194`). `provision_domain_user_and_org` (`app/auth.py:152-201`) joins any pre-existing domain user/org with that email before verification.
- The victim then (a) clicks the verification mail: `verify_email` (`:290-295`) flips `email_verified` but keeps the attacker's `password_hash` and sessions; (b) signs in with Google/GitHub: linking is refused while unverified (good) but, after (a), links silently (`app/auth.py:245-252`); (c) resets the password (`:277-287`): sets `email_verified=True` but does not revoke existing `AuthSession` rows, so the attacker's session stays valid for 14/30 days. In every path the attacker keeps access to an account the victim believes is theirs (and to its workspace/org).
- Fix: no session until the email is verified (or a restricted state); on verify, reset-password and first OAuth link clear any pre-verification password and revoke all sessions of the user; do not attach to an existing org before verification.

### A-08 (medium) HTML injection in outgoing mail

- `routes_auth.py:168,173` (`signup`), `:258` (`forgot-password`), `:310` (`resend`) interpolate `user.name` (user-controlled, up to 120 chars, `schemas.py:22`) into HTML bodies unescaped. Because the attacker picks the victim's email at signup (A-07), the victim receives a genuine Radius mail containing attacker markup (links, fake text).
- Fix: `html.escape(user.name)` everywhere.

### A-09 (medium) Deployment profile weakens security controls

- `docker-compose.yml:56-92` never passes `RADIUS_API_KEY_PEPPER` (only mentioned in `.env.example:25`; grep over compose, CI and scripts finds no forwarding). In the container `api_key_pepper` is empty, `ApiKeyService.enabled` is false (`api_keys.py:185-196`) and managed-key create/rotate fail, steering a compose deployment to the deprecated static `API_KEYS` (full access, unhashed).
- `SESSION_COOKIE_SECURE` defaults to `false` (`docker-compose.yml:86`, `app/config.py:26`) and the production guard (`app/config.py:309-326`) neither requires it nor covers `uat`: in the "production-like" profile the session and OAuth-flow cookies can travel over HTTP.
- Fix: forward the pepper (and refuse to start in production with neither pepper nor `API_KEYS`); require `session_cookie_secure=True` in production/uat in `_production_guards`.

### A-10 (low) Missing session row gives a 500

- `app/routes_auth.py:122-125`: `session.expires_at` is read before the `not session` check at `:127`. A validly signed token whose session row no longer exists raises `AttributeError` (HTTP 500). Reorder the checks.

### A-11 (low) Webhook robustness

- `hmac.compare_digest(signature, expected)` (`github_webhooks.py:~726`) on `str` raises `TypeError` for non-ASCII header values (ran: "comparing strings with non-ASCII characters is not supported"): an unauthenticated request gets 500 rather than 403. Compare `.encode()` bytes.
- `int(repo_data["id"])` in `_resolve_webhook_organization_id` (`:~690`) runs outside the handler's try/except for payload errors: a signed but odd payload gives 500.
- The whole body (limit 25 MiB, `config.py:99`) is read before the signature check (`:73-75`); 600 requests/min/IP allows heavy memory pressure from unauthenticated callers. Lower the pre-auth limit or hash while streaming.
- The delivery id is recorded only after processing (`:~154-160`): concurrent redeliveries both process (duplicate work). Signed payloads carry no timestamp, so replay with a new delivery id is accepted (inherent to GitHub's scheme).

### A-12 (low) Login hygiene and rate limiting

- `login` (`routes_auth.py:183-188`) skips argon2 for unknown users: response time reveals existence; `signup` returns 409 for existing emails (`:144-148`).
- The `auth` bucket is per IP only (`rate_limit.py:226-229`, `keyed` excludes `auth`): no per-account throttle (distributed credential stuffing). Without `RADIUS_TRUSTED_PROXIES` every user behind one reverse proxy shares one 10/min bucket. Limits are per process (documented).
- `Login` reuses the password-strength validator (`schemas.py:21-33`), so older or weaker passwords get 422 at login.

### A-13 (low) `.`/`..` accepted as owner/name

- `parse_owner_repo` (`github_pull.py:53-70`) allows `.` in names, so `../..` is accepted. `GitHubAppClient._request` uses `urljoin` (`client.py:420-423`), which collapses dot segments (ran: `repos/../app/installation` becomes `https://api.github.com/app/installation`). The caller can steer GET requests (App JWT or installation token) to other API paths; impact is small (GET only, response shape checked) but cheap to close: reject `.`/`..` segments and `quote()` owner/repo/ref in `client.py` as `intent_sources.py:429` already does.

### A-14 (low) Non-atomic single-use tokens

- `consume_action_token` (`app/auth.py:110-138`) selects, tests `used_at`, then sets it; two concurrent requests with the same reset token both succeed. Use `UPDATE ... WHERE used_at IS NULL` and check `rowcount`.

### A-15 (low) Unbounded session creation

- `/auth/refresh` (`routes_auth.py:220-227`) creates a new `AuthSession` per call, never revokes the previous one, and is excluded from rate limiting (`rate_limit.py:107`). A stolen cookie can mint sessions indefinitely; row bloat. Rotate (revoke the old one). `remember` is also dropped by refresh.

### A-16 (low) Misc secret and switch hygiene

- `should_auto_verify_email` (`app/auth.py:29-36`) honours `DEV_AUTO_VERIFY_EMAIL` in any environment (compose passes it through, `docker-compose.yml:88`): setting it in production verifies every signup, defeating the OAuth link rule. Gate on `RADIUS_ENV`.
- `_may_log_action_tokens` (`:39-47`) treats an unset `RADIUS_ENV` as development and prints verification/reset links; with the public default `session_secret` (`app/config.py:22`) a mis-set environment fails open (forging a session also needs a real `sid`, so not directly exploitable).
- `send_email_message` prints recipient addresses and SMTP exception text to stdout (`routes_auth.py:60-78`).
- `/metrics` is exempt from rate limiting and unauthenticated when enabled (`observability.py:61`).
- 403 for another org's repo vs 404 for an unknown id (`repositories.py:143-144` and similar) lets tenants probe which UUIDs exist; the intent and verdict-v2 routes already return a uniform 404.

### A-17 (low) Sandbox residue

- `junit_parser.py:140-150` and `result_matching.py:23-24` fall back to stdlib `xml.etree` when `defusedxml` is missing (declared in `pyproject.toml:36`, so low). Size is capped (20 MiB) but entity expansion is not prevented in the fallback.
- `sandbox_runner.py` `_run_once` makes the host results directory `0o777`; on a shared host any local user can plant files (symlinks are rejected on read, `_read_artifact`).
- By design, test outcomes are produced by PR-controlled code (a `conftest.py` can emit any JUnit file or exit code) and CI uploads are bound only to the commit sha; the verdict is not tamper-proof evidence of test success.

---

## Areas reviewed and found sound

- **OAuth flow** (`app/oauth.py`, `routes_auth.py:374-479`): PKCE S256 with a server-held verifier; `state` and flow id stored hashed (PBKDF2 with a fixed salt is adequate for 256-bit random inputs) and compared with `compare_digest`; the flow row is deleted before any check so attempts are single use (SELECT then DELETE with `rowcount` check is race-safe); flow cookie is httponly, lax, path-scoped, 10 min TTL; provider mismatch and expiry rejected.
- **ID token validation**: RS256 only (HS*/none refused before key lookup, so no algorithm confusion; the key is an RSA public key chosen by `kid`), `iss` allowlist, `aud` via PyJWT plus `azp` for multi-audience, `exp`/`iat`/`sub` required with 60 s leeway, nonce compared constant-time, `email_verified is True` strict. JWKS cache: per URL, 1 h TTL, refetch at most once a minute, response size cap, only RSA/sig/RS256 keys accepted; forged-`kid` floods cannot hammer the provider.
- **Account linking** (`app/auth.py:209-260`): identity keyed by `(provider, sub)`; email used only for unknown identities and only when provider-verified; link refused if the local account is unverified; GitHub uses only `/user/emails` primary+verified, never the public profile email; IntegrityError race handled.
- **Redirects**: `redirect_uri` comes only from settings and is shape-checked (https in production, exact path); `next` is validated (no `//`, backslash, control chars, scheme/netloc, also after one percent-decode) and is appended to the configured frontend origin anyway, so no open redirect. Error redirects use a fixed allowlist of codes; failures log only the code, not tokens or provider bodies.
- **Sessions and cookies**: HS256 JWT pinned to `algorithms=["HS256"]`; the token needs a live server-side `AuthSession` row (random `sid`), so a leaked or default secret alone cannot forge a session; HttpOnly + SameSite=Lax; logout revokes the row; CSRF is mitigated by SameSite=Lax, JSON-only bodies (415 middleware) and an explicit CORS allowlist (no `*` with credentials).
- **Managed API keys** (`api_keys.py`, `token_fingerprint.py`): 256-bit random token, HMAC-SHA256 with server pepper, constant-time compare with a dummy-hash path for unknown/revoked/expired keys, org-scoped lookups, scopes validated against a closed set, expiry and immediate revocation honoured, rotation overlap bounded, audit events without secrets, token shown once. Scope enforcement is centralized in `get_api_principal` by method/path (admin for `/api-keys`, ci-upload for the two upload POSTs, read for safe methods, write otherwise) and `/api-keys` routes re-check admin. Legacy env keys use `compare_digest`; with no keys configured it fails closed unless the dev flag is on and `RADIUS_ENV` is development/test.
- **Tenant isolation, other routes**: analyses, graph, tests, confidence, intent, verdict-v2 and repositories (get/patch/delete/PRs/sync/analyze) all resolve the analysis/repository and check the organization; list endpoints filter by the principal's org; intent and verdict-v2 return uniform 404s; the intent store takes the org explicitly.
- **Webhook signature**: HMAC-SHA256 over the raw bytes with `compare_digest`; fails closed with no secret outside the explicit dev flag; JSON object enforced; unknown installations rejected unless explicit single-tenant mode; per-org idempotency keyed by delivery id with body-hash mismatch detection; webhook-derived clone URLs are built from GitHub-signed payloads.
- **HTTP hardening**: CORS allowlist (https-only and no `*` validated in production); body-size limits enforced by Content-Length and while streaming (413 rewrite even after the app started); JSON content-type enforcement; security headers on every response including errors; rate limiter hides raw API keys behind a salted hash and counts per IP and per key; trusted-proxy X-Forwarded-For walk is right-to-left and not spoofable.
- **Sandbox runner**: network none, read-only rootfs, tmpfs, non-root uid, all caps dropped, no-new-privileges, pids/memory/CPU/ulimits, seccomp never `unconfined`, `--pull never`, command placed after the image, fixed env allowlist (no host env), workspace is a read-only copy with `.git` removed and symlinks not followed, output watchdog and timeout kill, fail-closed readiness check, artifacts read only as regular non-symlink files. Worker default mode is `disabled`; `unsafe_in_process` is refused in uat/production. The mutation runner writes mutants into a snapshot, checks `resolve().relative_to(workspace)`, validates test ids, and its local backend needs an explicit opt-in env.
- **GitHub client**: App JWT is short-lived RS256 and never logged; error bodies are truncated; only idempotent methods are retried on transient errors (rate-limit rejections are retried for POST, which is safe) with a bounded total wait; the poller uses the owning org's installation token, isolates per-repo failures and caps work per tick; cross-repo issue fetching is off by default and paths are quoted in the intent sources.
- **Secrets in logs**: git credentials go through the child process environment (not argv, remote URL or `.git/config`) and are scrubbed from errors; `redact_secrets` is applied to publish/poll errors; production config validators reject the published placeholder `SESSION_SECRET` and `EMAIL_DELIVERY_MODE=log`.

## Not reviewed or limited

- No end-to-end run of the API or worker (no Docker, DB or network); A-01's repro covers the git behaviour only, the route-to-worker path is by reading.
- `radius_github/rate_limit.py`, `publisher.py`, `pull_sync.py` internals, the intent text sanitizers (ReDoS), Alembic migrations (unique constraints on `github_repository_id`, API key prefix), the `packages/shared` DB layer, verdict-v2 worker code, worker job claiming, and the Next.js dashboard/CSRF handling were skimmed or not opened.
- GitHub's own behaviour (PKCE support for OAuth Apps, installation lookup semantics) was not verified.
