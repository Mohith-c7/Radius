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
| `installation` (`created`), `installation_repositories` (`added`) | Connects the listed repositories (reactivating ones that were removed earlier) and marks the organization's installation `active`. Installation payloads carry no default branch, so a provisional `main` is stored until the first push/PR delivery corrects it. Always delivered to an App; you do not subscribe to them |
| `installation` `deleted` | Marks the organization's installation `deleted` (`organizations.github_installation_status`) and **disconnects every repository of that organization** (rows, PRs and analyses are kept: inactive, never hard-deleted). Queued-not-started analyses are cancelled. Later `push`/`pull_request` deliveries get `202` with `ignored: true, ignoredReason: installation_deleted`. Reinstalling (a new `installation.created`, possibly under a new installation id) reactivates it |
| `installation` `suspend` / `unsuspend` | `suspend`: status `suspended`, queued-not-started analyses cancelled, repositories stay connected; deliveries are ignored with `installation_suspended`. `unsuspend`: back to `active` |
| `installation_repositories` `removed` | Disconnects just those repositories (only if they belong to the delivery's organization), cancels their queued-not-started analyses; later deliveries get `ignoredReason: repository_disconnected`. Running jobs are never killed |
| `push` | Upserts the branch's latest commit. No analysis |
| `pull_request` `opened`, `reopened`, `synchronize`, `ready_for_review` (non-draft) | Upserts the PR and starts (or reuses) an analysis for the head SHA |
| `pull_request` `closed` (merged or not) | Upserts the PR, returns `ignored: true`, and **cancels queued-not-started analyses** for that PR (`cancelledAnalysisIds` in the response). A running analysis is never killed; it finishes and publishes. Reopening starts a fresh analysis |
| `pull_request` `edited` | Upserts the PR, returns `ignored: true` (no analysis), and, IN-02, refreshes the PR title/body stored as intent for the PR's latest analysis from the payload (a new snapshot version only if the text changed) |
| `pull_request` other actions (`labeled`, draft, ...) | Upserts the PR (title, status) and returns `ignored: true`; no analysis |
| `issues` `edited` | 202, `ignored: true`; IN-02 refreshes the stored text of that issue (same repository) in the latest analysis of recent PRs that already link it. Other `issues` actions, and inactive installations: ignored |
| `issue_comment`, `check_run` | **Accepted and ignored** (202, `ignored: true`) |

**`issues: read` and the `issues` / `issue_comment` / `check_run` events.** Since IN-02 the worker reads linked issues with `GET /repos/{owner}/{repo}/issues/{n}` (needs `issues: read`), the PR commit list and `.radius/intent.yml` (`pull_requests` and `contents` read, already granted); the API refreshes stored issue text on `issues.edited` from the payload. Adding a permission later forces every installation owner to re-approve the App, so `issues: read` is requested from the start. `--minimal` drops it: the run still works and linked issues are recorded as *absent* with reason `forbidden` (not as errors), which is also a useful scenario. `issue_comment` and `check_run` stay ignored; capturing their real payloads gives fixtures.

Permissions actually exercised: `checks: write` (create/update/list Check Runs), `pull_requests: write` (comments), `contents: read` (clone via installation token; `.radius/intent.yml` via the contents API), pull request read (PR and commit list for intent), `issues: read` (linked issues, IN-02), `metadata: read`.

Publishing facts that shape the assertions:

- The check run is named `Radius confidence`. There is one per head SHA; republishing the same SHA updates it, a new push creates a new one on the new SHA (GitHub scopes check runs to a commit).
- The worker opens the `Radius confidence` check run as `in_progress` when it starts a job (best-effort: a publish failure is logged and never fails the analysis; skipped when `GITHUB_PUBLISH_RESULTS=false`), then completes the **same** run: with the verdict on success, or `neutral` ("analysis failed") when the final attempt fails or the result cannot be published. A job that is retried keeps the one run `in_progress` until the last attempt. A job cancelled before it starts never creates a check run.
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
| `RADIUS_FEATURE_INTENT_INGESTION` | api, worker | **Default `false`. Set it to `true` in both for the live run** (IN-02: intent from the PR) |
| `RADIUS_INTENT_ALLOW_CROSS_REPO` | worker | `false` (default); closing references to other repositories are recorded absent (`cross_repo_disabled`). Set `true` only to test that path |
| `RADIUS_INTENT_MAX_API_CALLS`, `RADIUS_INTENT_DEADLINE_SECONDS`, `RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS` | worker | `15`, `30`, `false` |

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

## 6b. Intent ingestion (IN-02): what to check during the live run

Everything below was built and tested against hand-built fixtures and a fake GitHub; **none of it has run against real GitHub yet.** Record what differs in `REPORT.md` and turn real payloads and responses into fixtures (`packages/github/tests/fixtures/webhooks/` and `.../fixtures/api/`). Set `RADIUS_FEATURE_INTENT_INGESTION=true` for the API and the worker first (it is off by default until this validation), restart both, then optionally `RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS=true`.

Setup in the sandbox repo (once): create issues #A and #B (any body with a sentence like "The helper must reject empty names."), add `.radius/intent.yml` on the PR branch (`version: 1` and one criterion), and open the PR with a body such as:

```
Adds greet().

Fixes #A
Closes <owner>/<repo>#B

<!-- template note that must not reach Radius -->
## Acceptance Criteria
- [ ] greet("") raises ValueError
```

Then check (database, or `GET /api/v1/analyses/<analysisId>/intent` with the API key headers):

| # | Check | Expected | If it differs |
| --- | --- | --- | --- |
| 1 | The `pull_request` delivery has a `body` key | stored `pr-body` comes from the payload; the worker makes no `GET /pulls/<n>` call | Payload shape differs from the fixtures: fix `GitHubPullRequestPayload` and the fixture |
| 2 | Worker log line `Intent ingestion` for the analysis | `intent_sources` lists `pr-title`, `pr-body`, `commits`, `intent.yml`, `issue:<A>` (`Closes <owner>/<repo>#B` is the PR's own repository here, so it is `issue:<B>`; a link to a different repository must be `absent` / `cross_repo_disabled` with no request made) as `present`; `intent_api_calls` <= 15 | Read `intent_diagnostics` and the per-source `reason` |
| 3 | App without `issues: read` (use `--minimal` or revoke it) | issue sources `absent` / `forbidden` (GitHub answers 403 `Resource not accessible by integration`, or 404 for a repository the token cannot see); the analysis still completes and the check run publishes | Record the real status and body; adjust `intent_rest.GitHubRestReader._classify` |
| 4 | Rate-limit shape | Not expected in a sandbox. If seen: 403 with `x-ratelimit-remaining: 0` or 429 `retry-after` becomes `unavailable` / `rate_limited` and stops further calls | Capture headers and body |
| 5 | Commit list | `commits` source: one `Commit <sha7>:` section per non-merge commit, no `Co-authored-by` / `Signed-off-by` lines; a merge commit from "Update branch" is skipped | Compare with `GET /pulls/<n>/commits` |
| 6 | Spec file | `intent.yml` present with the criterion; a new commit that removes the file gives a new analysis with `intent.yml` absent / `not_found` | 404 versus another status for a missing path or `ref` |
| 7 | Edit the PR body (`edit_description` scenario or by hand) | `pull_request.edited` delivery 202 `ignored`; no new check run or comment; snapshot version +1 in `GET .../intent` | Verify `changes.body.from` and that `pull_request.body` is the new text |
| 8 | Edit the issue text | `issues.edited` delivery 202; stored `issue:<A>` text changes and the version increments; saving without changes adds none | Confirm the `issues` event is subscribed and carries `issue.body` |
| 9 | Add `Fixes #C` to the body after the analysis ran | NOT fetched until the next analysis (known limitation); `pr-body` text is updated | See the follow-ups in `packages/intent/README.md` |
| 10 | Push a new commit | New analysis; its intent has the new commit list and the spec at the new SHA | |
| 11 | Redeliver an event | Replayed response, no new version | |
| 12 | Suspend the installation | New deliveries ignored (`installation_suspended`); the worker skips the job; no intent change | |
| 13 | ETag | A second ingestion of the same PR in the same worker process shows 304s (the cache is per process) | GitHub may not return ETags on every endpoint; check the `etag` headers |
| 14 | Hidden text | A body with a zero-width character, an RTL override and `<span hidden>` text | Stored text has none of them; `suspicious_content_removed=true` on the source |
| 15 | API-call count | `intent_api_calls` matches the requests GitHub saw (compare `x-ratelimit-used` if you capture it) | |

Not covered by the scenario script: its checks look at GitHub-visible effects (check runs, comments), and intent is visible only through the Radius API or database, so no scenario was added. Checks 7 and 8 are the manual equivalents of `edit_description`.

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
| Worker fails cloning a private repo | The clone authenticates with HTTP Basic, username `x-access-token`, password = the installation token (GitHub's documented git-over-HTTPS form). The token is handed to git through the child process environment (`GIT_CONFIG_*`, scoped to the remote's origin), so it is not on the command line, in `.git/config` or in logs. Check the App has `contents: read` and is installed on the repository; confirm live (section 7) |
| Check run stays missing for a draft PR | Drafts are ignored until `ready_for_review` |
| No intent for an analysis | `RADIUS_FEATURE_INTENT_INGESTION` not set to `true` (the default is off), empty App credentials in the worker, or an inactive installation; look for `Intent ingestion` / `Intent ingestion failed` in the worker log (failures never fail the analysis) |
| Linked issues missing from the intent | The App lacks `issues: read` (absent / `forbidden`), the issue is in a repository the installation cannot see (`not_found`), or the keyword sits inside a code fence, quote or HTML comment |
