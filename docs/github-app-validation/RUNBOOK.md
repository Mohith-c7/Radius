# F-06 runbook: validate the GitHub App against a live installation

Goal: prove webhook -> analysis -> Check Run + PR comment on a real repository, with idempotent redelivery. Everything below that does not need your browser is scripted; the browser clicks are marked **[OWNER CLICK]**.

Use a throwaway sandbox repository you own (private is fine). Do not point this at a production repo or a real customer installation.

Files in this folder:

| File | Purpose |
| --- | --- |
| `app-manifest.json` | GitHub App manifest template (placeholders `__WEBHOOK_URL__`, `__REDIRECT_URL__`, `__APP_NAME__`) |
| `../../scripts/github_app_manifest.py` | Serves the manifest-flow page, exchanges the code, writes credentials outside the repo |
| `../../scripts/github_app_scenarios.py` | Drives the scenarios with `gh` and writes evidence |
| `REPORT_TEMPLATE.md` | Copy to `REPORT.md` and fill in |
| `evidence/` | Generated scenario logs (commit them) and screenshots |

## 0. What the code really does (read first)

Verified in `apps/api/src/radius_api/routes/github_webhooks.py` and `packages/github/src/radius_github/`.

Endpoint: `POST /api/v1/webhooks/github` (the older `/api/v1/github/webhooks` in some docs was wrong and has been corrected in `docs/DEPLOYMENT.md`). Signature header `X-Hub-Signature-256` is mandatory unless `RADIUS_ALLOW_INSECURE_DEV=true` in a dev/test `RADIUS_ENV`; the Compose stack runs `RADIUS_ENV=production`, so the secret is required.

| Event | What Radius does |
| --- | --- |
| `ping` | Acknowledged (202), no tenant lookup |
| `installation` (`created`), `installation_repositories` (`added`) | Connects the listed repositories. Always delivered to an App; you do not subscribe to them |
| `push` | Upserts the branch's latest commit. No analysis |
| `pull_request` `opened`, `reopened`, `synchronize`, `ready_for_review` (non-draft) | Upserts the PR and starts (or reuses) an analysis for the head SHA |
| `pull_request` other actions (`edited`, `closed`, `labeled`, draft, ...) | Upserts the PR (title, status) and returns `ignored: true`; no analysis |
| `issues`, `issue_comment`, `check_run` | **Accepted and ignored** (202, `ignored: true`) |

**Mismatch to know about:** the F-06 task lists `issues`, `issue_comment`, `check_run` events and `issues: read`. Nothing in the code acts on them or calls an issues-read endpoint (PR comments use the Issues comments API, which `pull_requests: write` covers for PRs). `app-manifest.json` includes them anyway so that real payloads can be captured as fixtures; `--minimal` drops them. Either choice validates the same behaviour.

Permissions actually exercised: `checks: write` (create/update/list Check Runs), `pull_requests: write` (comments), `contents: read` (clone via installation token), `metadata: read`.

Publishing facts that shape the assertions:

- The check run is named `Radius confidence`. There is one per head SHA; republishing the same SHA updates it, a new push creates a new one on the new SHA (GitHub scopes check runs to a commit).
- `publish_in_progress` exists but is **not called by the worker**, so there is no `in_progress` check run during analysis; the check appears once, already `completed`.
- The PR comment contains `<!-- radius-confidence-report -->` and is edited in place (only bot-authored comments are edited).
- Conclusion is `success` only for a `verified` verdict with low/medium risk; otherwise `neutral` (a sandbox repo with no tests will normally be `neutral`, which is correct, not a failure).

## 1. Prerequisites

- Docker Desktop with Compose v2, `uv`, `git`, `gh` (logged in as the sandbox repo owner: `gh auth status`), Python 3.12.
- A sandbox repository with a Python file (any) on its default branch, e.g. create `me/radius-sandbox` with a README and `app.py`.
- `gh` token scopes: `repo`. Nothing else is needed.

## 2. Public webhook URL for local dev

The App must reach `http://localhost:8000/api/v1/webhooks/github`.

### Option A (recommended): cloudflared quick tunnel

Raw passthrough, so HMAC signatures survive unchanged.

```powershell
winget install Cloudflare.cloudflared          # macOS: brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

It prints `https://<random>.trycloudflare.com`. Your webhook URL is that plus the path:

```
https://<random>.trycloudflare.com/api/v1/webhooks/github
```

The hostname changes every run. If it changes, update the App: Settings > Developer settings > GitHub Apps > your app > General > Webhook URL.

### Option B: smee.io

Open https://smee.io/new **[OWNER CLICK]** to get `https://smee.io/<channel>`; that is the webhook URL (no path). Forward it locally:

```bash
npx smee-client --url https://smee.io/<channel> --path /api/v1/webhooks/github --port 8000
```

Caveat: smee-client re-serializes the JSON body. A payload containing characters GitHub escapes differently (for example `<`, `>`, `&` in a PR title or body) can then fail HMAC verification with 403. Keep PR text plain ASCII, or use option A.

## 3. Create the GitHub App (manifest flow)

1. Start the tunnel (section 2) and note the full webhook URL.
2. Run the helper from the repo root. `--out` must be outside the repo (the helper refuses otherwise):

   ```bash
   uv run python scripts/github_app_manifest.py \
     --webhook-url "https://<random>.trycloudflare.com/api/v1/webhooks/github" \
     --name "Radius Sandbox F-06 <your-handle>" \
     --out ~/radius-github-app
   ```

   Add `--org <org>` to create it under an organization, `--minimal` for only `pull_request`/`push`, `--print-manifest` to just inspect the manifest (no server, no network).
3. **[OWNER CLICK]** The browser opens `http://localhost:3456/`. Review the permissions and click "Create GitHub App on GitHub", then confirm the name on GitHub.
4. GitHub redirects to `localhost:3456/callback`; the helper exchanges the one-time code and writes, with owner-only permissions, never overwriting:
   - `~/radius-github-app/radius-github.env`: `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET` (generated by GitHub), `GITHUB_APP_PRIVATE_KEY` (single line with `\n`), `GITHUB_PUBLISH_RESULTS=true`, `GITHUB_SINGLE_TENANT=true`.
   - `~/radius-github-app/app.pem`
   Secrets are not printed. On Windows the file mode is advisory; keep the folder under your user profile.
5. Open the App's settings page and confirm Permissions & events match section 0. Under Advanced, the **Recent Deliveries** tab should show nothing yet.

Manual fallback (no helper): GitHub > Settings > Developer settings > New GitHub App; set webhook URL and a random secret (`openssl rand -hex 32`), the permissions above, subscribe to events, generate a private key, and write the same env lines yourself.

## 4. Install the App on the sandbox repo

**[OWNER CLICK]** Open `https://github.com/apps/<slug>/installations/new` (printed by the helper), choose "Only select repositories", pick the sandbox repo, Install. Note the installation id from the URL (`.../installations/<id>`); it is optional because the API records it from the first delivery.

## 5. Configure and run Radius

Env vars (names match `.env.example`, `apps/api/src/radius_api/config.py`, `apps/worker/src/radius_worker/config.py`, `packages/github/src/radius_github/client.py`):

| Variable | Used by | Value |
| --- | --- | --- |
| `GITHUB_APP_ID` | worker | from `radius-github.env` |
| `GITHUB_APP_PRIVATE_KEY` | worker | single line with `\n` (client expands `\n`); keep single quotes in `.env` so Compose does not mangle it |
| `GITHUB_WEBHOOK_SECRET` | api | from `radius-github.env` |
| `GITHUB_PUBLISH_RESULTS` | worker | `true` |
| `GITHUB_SINGLE_TENANT` | api | `true` (otherwise a first delivery from an unlinked installation is rejected 403; there is no other way yet to link an installation to an organization) |
| `GITHUB_DEFAULT_ORGANIZATION_ID` | api | UUID of an **existing** organization row (see below) |
| `GITHUB_INSTALLATION_ID` | worker | optional; if empty the worker uses the installation id the API stored on the organization |
| `DASHBOARD_BASE_URL` | worker | `http://localhost:3000` (link in the check run) |
| `GITHUB_API_BASE_URL`, `GITHUB_API_VERSION`, `GITHUB_TIMEOUT_SECONDS` | worker | defaults |

Steps (see `docs/DEVELOPMENT_GUIDE.md` quickstart):

```bash
make env                                   # creates .env if missing (Windows: .\scripts\dev.ps1 env)
# append the lines from ~/radius-github-app/radius-github.env to .env (do not commit .env)
make dev                                   # Windows: .\scripts\dev.ps1 dev
```

`GITHUB_SINGLE_TENANT` is passed through to the API by `docker-compose.yml` (added by F-06). Use SQL storage (the Compose default): with `STORAGE_BACKEND=memory` the API and worker are separate processes and cannot share the queue, so `make dev-local` cannot run this validation.

The organization row must exist, otherwise the first repository insert fails on its foreign key. `make env` sets `GITHUB_DEFAULT_ORGANIZATION_ID=00000000-0000-4000-8000-000000000001`, and nothing creates that row outside demo seeding (which is ignored in production). Create it once:

```bash
docker compose exec postgres psql -U radius -d radius -c \
  "INSERT INTO organizations (id, name, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000001', 'F-06 Sandbox', now(), now()) ON CONFLICT DO NOTHING;"
```

Check health and wiring:

```bash
curl -f http://localhost:8000/api/v1/health
docker compose logs -f api worker
```

Smoke test the tunnel: in the App settings > Advanced > Recent Deliveries, redeliver the `ping` (or wait for the `installation` delivery). Expect HTTP 202 and, in the worker/API logs, "Webhook delivery handled". 403 means a wrong secret or a body altered by the tunnel; 502 means the API is not up.

After installation the `installation` event connects the sandbox repo (default branch is recorded as `main`, see defects in `REPORT_TEMPLATE.md`). Confirm the organization got the installation id:

```bash
docker compose exec postgres psql -U radius -d radius -c "select id, github_installation_id from organizations;"
```

## 6. Run the scenarios

Dry run first (default; nothing is touched):

```bash
uv run python scripts/github_app_scenarios.py --repo me/radius-sandbox
```

Execute (creates a branch and a PR in the sandbox repo, up to roughly 15 minutes):

```bash
uv run python scripts/github_app_scenarios.py --repo me/radius-sandbox --yes \
  --app-id <GITHUB_APP_ID> --app-key-file ~/radius-github-app/app.pem --cleanup
```

`--app-id/--app-key-file` enable the redelivery scenario (the App deliveries API needs an App JWT, minted locally, never printed). Without them the scenario is marked SKIPPED and you do it by hand (below). Omit `--cleanup` to keep the PR open for screenshots. Useful knobs: `--only open_pr push_commit`, `--timeout 600`, `--quiet-seconds 45`.

What each scenario asserts:

| Scenario | Expected |
| --- | --- |
| open_pr | One completed `Radius confidence` check run on the head SHA; exactly one bot comment containing the marker |
| push_commit | New head SHA has its own completed check run; same single comment id (edited in place) |
| edit_description | No new check run, no new comment (`edited` is ignored) |
| close_reopen | No duplicates; check run for the head SHA still exactly one |
| force_push | New SHA gets a completed check run; still one comment; the orphaned SHA keeps its old check run (GitHub behaviour) |
| redeliver | Redelivery answers 202 with the replayed stored response; no new check run or comment |

Manual redelivery and manual duplicate check:

1. **[OWNER CLICK]** App settings > Advanced > Recent Deliveries > open the latest `pull_request` delivery > Redeliver. The `X-GitHub-Delivery` GUID stays the same, so Radius must replay.
2. Count bot comments and check runs:

   ```bash
   gh api repos/me/radius-sandbox/issues/<n>/comments --jq '[.[]|select(.body|contains("radius-confidence-report"))]|length'
   gh api repos/me/radius-sandbox/commits/<sha>/check-runs --jq '[.check_runs[]|select(.name=="Radius confidence")]|length'
   ```
   Both must print `1`.

## 7. Evidence and report

1. The scenario script wrote `docs/github-app-validation/evidence/scenarios-<timestamp>.md`.
2. **[OWNER CLICK]** Take screenshots (PR conversation showing the single comment, Checks tab, App Recent Deliveries with 202s and the redelivery). Save them in `evidence/` and link them.
3. Copy `REPORT_TEMPLATE.md` to `REPORT.md` and fill it in. File defects as issues and link them.
4. Save each real delivery payload (App settings > Advanced > a delivery > Payload; remove anything private) and add or update fixtures under `packages/github/tests/fixtures/webhooks/`; the tests in `apps/api/tests/test_github_webhook_fixtures.py` pick up new names with a one-line addition. Do not include secrets.
5. Revoke when done: delete the App (Settings > Developer settings) or at least uninstall it, and delete `~/radius-github-app`. Remove the lines from `.env`.

## 8. Troubleshooting

| Symptom | Cause |
| --- | --- |
| Delivery 403 `Invalid GitHub webhook signature` | Wrong `GITHUB_WEBHOOK_SECRET` in the API container (restart after editing `.env`), or smee re-serialized the body |
| Delivery 403 `Unknown GitHub installation` | `GITHUB_SINGLE_TENANT` is not `true` in the API container |
| Delivery 500 on the first repo insert | The organization row for `GITHUB_DEFAULT_ORGANIZATION_ID` does not exist (section 5) |
| Analysis runs but nothing appears on GitHub | `GITHUB_PUBLISH_RESULTS=false`, or `GITHUB_APP_ID`/`GITHUB_APP_PRIVATE_KEY` empty in the worker; publish errors are logged as "Could not publish GitHub Check Run or PR comment" |
| Worker fails cloning a private repo | See "unverified until live" in `REPORT_TEMPLATE.md`: the clone sends `Authorization: Bearer <installation token>`; GitHub normally expects Basic auth with `x-access-token` for git over HTTPS |
| Check run stays missing for a draft PR | Drafts are ignored until `ready_for_review` |
