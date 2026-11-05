# Live GitHub demo without a webhook

Run Radius against a real GitHub repository **without a public URL, tunnel or webhook**. Radius pulls
from GitHub (outbound HTTPS only): you connect a repository by `owner/name`, point Radius at a pull
request, the worker analyzes it, and the verdict appears as one pull request comment and one Check
Run.

**Status: unverified against real GitHub.** The whole path is covered by `scripts/smoke_e2e.py`
(stage "pull-based GitHub") and unit tests that run the real `GitHubAppClient` (RS256 JWT signing
included) against an in-memory fake GitHub. Nobody has yet run it against `api.github.com`; GitHub
settings-page labels below are written from memory and may differ slightly. Run
`scripts/live_check.py` (step 5) before the demo: it is the first real-GitHub contact and reports
what is wrong.

What "pull-based" means here:

| Step | Webhook flow | Pull flow (this page) |
| --- | --- | --- |
| Radius learns the repository | `installation` / `pull_request` webhook | `POST /api/v1/repositories/connect-github` |
| Radius learns the installation id | webhook payload | discovered with the App JWT and stored on the organization, **only in single-tenant development mode** (`RADIUS_GITHUB_DEV_SINGLE_TENANT`, see below) |
| A pull request starts an analysis | `pull_request` webhook | `POST /api/v1/repositories/{id}/pull-requests/{n}/analyze` or `.../sync-pull-requests` |
| Worker clones, analyzes, publishes | same | same (outbound calls only) |

Everything after "start analysis" is the unchanged worker path. By default nothing triggers on push:
you start each analysis yourself (dashboard button or `analyze`). To have new commits picked up
automatically without a webhook, turn on the worker poller (section 7).

## 1. Create the GitHub App (webhook off)

GitHub: your avatar > Settings > Developer settings > GitHub Apps > New GitHub App. Use a personal
account and a throw-away test repository.

| Field | Value |
| --- | --- |
| GitHub App name | anything unique, e.g. `radius-demo-<yourname>` |
| Homepage URL | any URL (e.g. the repository URL) |
| Webhook > Active | **unchecked**. Webhook URL and secret stay empty. |
| Repository permissions | **Pull requests: Read and write**, **Checks: Read and write**, **Contents: Read-only**, **Metadata: Read-only** (mandatory, selected automatically) |
| Account permissions | none |
| Subscribe to events | none (nothing is delivered) |
| Where can this GitHub App be installed? | Only on this account |

Optional: **Issues: Read-only** lets the worker read linked issues when
`RADIUS_FEATURE_INTENT_INGESTION=true` (see RUNBOOK section 0). The demo works without it.

Create the App, then on its settings page:

1. Note the **App ID** (a number near the top of the "About" box).
2. Under "Private keys" choose **Generate a private key**. A `.pem` file downloads. Move it **outside
   the repository**, e.g. `~/radius-demo/app.private-key.pem` (Windows: `C:\Users\<you>\radius-demo\`).

Never commit the key, paste it into an issue or chat, or leave it in the repository folder: anyone
holding it can act as your App on every repository it is installed on. `.env` is git-ignored; `*.pem`
files are not, which is why the key stays outside the checkout. If it leaks, delete the key on the App
page and generate a new one.

## 2. Install it on one test repository

App settings page > Install App > your account > **Only select repositories** > pick the one test
repository > Install. Open a pull request on that repository (any small change on a branch) so there is
something to analyze. Draft pull requests are skipped by `sync-pull-requests`, so open a normal one.

## 3. Give Radius the credentials

Credentials go in `.env` at the repository root (git-ignored; `make env` creates it with random
local-dev secrets, see [INSTALL.md](INSTALL.md)). Both the **api** and the **worker** container need
them; `docker-compose.yml` forwards them to both.

```dotenv
GITHUB_APP_ID=123456
# Single line, newlines written as \n, wrapped in single quotes (see RUNBOOK section 5 for the quoting rule):
GITHUB_APP_PRIVATE_KEY='-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----'
RADIUS_FEATURE_VERDICT_V2=on
GITHUB_PUBLISH_RESULTS=true
```

Print the single-line form of your key (copy the output into `.env`; it is a secret, do not paste it
anywhere else; it handles Windows line endings):

```bash
python scripts/live_check.py --env-line ~/radius-demo/app.private-key.pem
```

Running the API and worker natively (`make dev-local`, no Docker) can use the file directly instead:
`GITHUB_APP_PRIVATE_KEY_PATH=/home/you/radius-demo/app.private-key.pem` (used only when
`GITHUB_APP_PRIVATE_KEY` is empty). Compose does not mount the file into containers, so with Docker use
the single-line variable.

You do **not** need `GITHUB_WEBHOOK_SECRET`, `GITHUB_INSTALLATION_ID`, a public URL or a tunnel. The
installation id is discovered when you connect the repository. (`GITHUB_INSTALLATION_ID`, if set, wins
and is used for every organization.)

**Single-tenant development mode.** GitHub answers "which installation covers `owner/name`?" for every
repository of every customer of a shared App, so Radius does not attach a discovered installation to an
organization on the strength of a repository name alone (security review A-03,
[../security/INSTALLATION_BINDING.md](../security/INSTALLATION_BINDING.md)). The discovery above works
because `make dev` runs the API with `RADIUS_ENV=development`, where `RADIUS_GITHUB_DEV_SINGLE_TENANT`
defaults to **on** (it defaults to off in every other environment). If your API runs with another
`RADIUS_ENV`, set `RADIUS_GITHUB_DEV_SINGLE_TENANT=true` explicitly, and only when exactly one organization
uses this App. Without it, `connect-github` answers `403 GITHUB_INSTALLATION_NOT_LINKED` for an organization
that has no installation yet. Even in dev mode an installation already linked to another organization is
never taken (`409 GITHUB_INSTALLATION_MISMATCH`). Repository clone URLs must be `https://github.com/...`
(or the host in `RADIUS_GIT_ALLOWED_HOSTS`, for GitHub Enterprise Server).

## 4. Start the stack

```bash
make dev                      # or: .\scripts\dev.ps1 dev   (Windows PowerShell)
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml ps
```

Check that the variables reached both containers without printing the key:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml exec api   sh -c 'echo "api:    app=$GITHUB_APP_ID key_len=${#GITHUB_APP_PRIVATE_KEY} v2=$RADIUS_FEATURE_VERDICT_V2"'
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml exec worker sh -c 'echo "worker: app=$GITHUB_APP_ID key_len=${#GITHUB_APP_PRIVATE_KEY} v2=$RADIUS_FEATURE_VERDICT_V2"'
```

Both lines must show your App ID, a key length above 1000 and `v2=on`.

## 5. Preflight against real GitHub (read-only)

Run on the host, before or after starting the stack:

```bash
GITHUB_APP_ID=123456 \
GITHUB_APP_PRIVATE_KEY_PATH=~/radius-demo/app.private-key.pem \
RADIUS_LIVE_REPO=your-user/your-test-repo \
  python scripts/live_check.py
```

It checks the App JWT, key format, clock skew, that the App is installed on that repository, the
permissions the installation actually has (`checks:write` among them), that the repository and its open
pull requests are readable, and prints PASS / WARN / FAIL per check. It creates no check run, comment or
file; the only non-GET call mints a short-lived installation token. Nothing secret is printed. Exit code
is 0 when nothing FAILed.

Example of the output shape, produced against the in-memory fake (not real GitHub) with `checks` set to
read-only, so it shows what a permission mistake looks like:

```text
[PASS] app jwt: GitHub accepted the App JWT (app: radius-demo).
[PASS] clock: local clock within 0s of GitHub.
[FAIL] installation permissions: the installation lacks: checks:write.
       -> App settings > Permissions & events: set Pull requests = Read & write, Checks = Read & write, ...
[FAIL] check-run write: checks permission is 'read', Radius cannot publish a Check Run.
[PASS] repository: acme/radius-demo readable (private, default branch main, id 4242).
[PASS] pull requests: 1 open (e.g. #3); readable.

PREFLIGHT FAILED: 9 pass, 1 warn, 2 fail
```

## 6. Connect the repository and analyze a pull request

Use the dev key from `.env` (`RADIUS_API_KEY`) and the dev organization id
(`GITHUB_DEFAULT_ORGANIZATION_ID`, `00000000-0000-4000-8000-000000000001`). On Windows PowerShell use
`curl.exe`, not the `curl` alias.

```bash
export API=http://localhost:8000/api/v1
export H1="X-Radius-Organization-Id: 00000000-0000-4000-8000-000000000001"
export H2="X-Radius-API-Key: $(grep '^RADIUS_API_KEY=' .env | cut -d= -f2-)"

# 1. connect by owner/name (finds the installation itself; safe to repeat)
curl -s -X POST "$API/repositories/connect-github" -H "$H1" -H "$H2" \
     -H 'Content-Type: application/json' -d '{"repository":"your-user/your-test-repo"}'
# -> 201 {"success":true,"data":{"id":"<repository-id>","full_name":"your-user/your-test-repo",...},
#         "meta":{"installationId":<n>,"created":true}}

# 2. analyze pull request #7 (reads the head commit from GitHub)
curl -s -X POST "$API/repositories/<repository-id>/pull-requests/7/analyze" -H "$H1" -H "$H2"
# -> 202 {"success":true,"data":{"id":"<analysis-id>","status":"pending","commit_sha":"<head sha>",...}}

# or: pull every open (non-draft) PR and analyze each one that has no analysis for its head commit
curl -s -X POST "$API/repositories/<repository-id>/sync-pull-requests" -H "$H1" -H "$H2"

# 3. wait a few seconds for the worker, then read the result
curl -s "$API/analyses/<analysis-id>" -H "$H1" -H "$H2"                 # status: completed
curl -s "$API/analyses/<analysis-id>/verdict-v2" -H "$H1" -H "$H2"      # needs RADIUS_FEATURE_VERDICT_V2=on
```

The same steps are available in the dashboard (section 7).

## 7. Demo from the dashboard, and automatic pickup of new commits

Everything in section 6 works from the dashboard at `http://localhost:3000` (the browser never sees the
API key; requests go through the same-origin proxy, which allows exactly these routes):

1. **Repositories** > "Connect GitHub repository": type `your-user/your-test-repo` (a github.com URL
   works too) and press Connect. Typos are caught in the form; API errors are shown in words with the
   next step (for example "The Radius GitHub App is not installed on this repository"). On success a
   link opens the repository. Connecting twice is safe ("already connected").
2. **Repository page** or **Pull requests**: "Sync Open PRs from GitHub" pulls the open pull requests
   and queues an analysis for each head commit that has none. The banner says how many pull requests
   were synced, how many analyses were queued, and lists every pull request that was skipped with
   the reason.
3. Every open pull request has an **Analyze** button: it reads the current head commit from GitHub and
   queues an analysis; "Open analysis" appears next to it.
4. On the analysis page, **Re-run analysis** queues a new analysis of the same commit (for example
   after you changed `.radius/intent.yml` or CI results). It shows API errors in the same way, for
   example when the repository was disconnected. To analyze a newer commit use Analyze or the poller;
   a re-run never moves to a newer head commit.

### Automatic pickup (optional poller)

Set in `.env` (the worker container) and restart the worker:

```dotenv
RADIUS_GITHUB_POLL_INTERVAL_SECONDS=60
```

`0` (default) is off; values below 30 are raised to 30. Every interval (plus or minus 10 percent
jitter) the worker lists the open pull requests of each connected repository whose installation it can
reach and queues an analysis for every head commit that has none yet. Drafts are not analyzed. It uses
the same code as `sync-pull-requests`, with these differences: a head commit whose analysis *failed*
is not retried automatically (use Re-run), and one tick queues at most
`RADIUS_GITHUB_POLL_MAX_ANALYSES_PER_TICK` analyses (default 10) over at most
`RADIUS_GITHUB_POLL_MAX_REPOSITORIES_PER_TICK` repositories (default 25); the rest wait for the next
tick. One failing repository does not stop the others, an installation that GitHub rate limits is left
alone until its reset, and SIGTERM ends the worker after the current job. The worker log shows
`GitHub pull request poller enabled` at start and one `GitHub poll tick finished` line per tick (with
`analyses_started`, `errors`, `deferred`). It needs `GITHUB_APP_ID` and the key in the **worker**
container; without them it logs `poll_disabled` and stays off.
Cost: one GitHub API call per polled repository per tick (conditional requests are not used yet).

Push a commit to the test pull request, wait up to one interval, and the new commit gets an analysis;
the existing pull request comment is updated in place and a Check Run appears on the new commit.

## 8. What you should see

The following was observed in `scripts/smoke_e2e.py` against the fake GitHub; on real GitHub the same
structure is expected, which is exactly what this demo is meant to confirm.

- Connect returns 201 with the repository name, default branch and clone URL read from GitHub, and
  `meta.installationId`. Connecting again returns 200 with `created: false`.
- The analysis goes `pending` then `completed`. The worker log shows no "Could not publish GitHub Check Run
  or PR comment" warning.
- On the pull request: **one** comment containing the Verdict v2 alpha disclaimer and a hidden
  `radius-verdict-v2` marker, and **one** Check Run named `Radius confidence` with the v2 alpha title whose
  details link points at `DASHBOARD_BASE_URL` (default `http://localhost:3000`, so the link only opens
  on your own machine).
- With no CI results uploaded and nothing confirmed, the first verdict is likely to be
  **insufficient evidence** (the fixture used by the smoke gave exactly that). That is the honest
  outcome for a pull request Radius has no test results for, not an error. The Check Run conclusion is
  advisory (`neutral`) unless a linked test failed. See [../verdict-v2.md](../verdict-v2.md) for how
  to read it, and the CI upload flow in [../CI_INTEGRATION_GUIDE.md](../CI_INTEGRATION_GUIDE.md).
- Calling `analyze` again for the same head commit while it is pending returns the same analysis.
  Repeating `sync-pull-requests` does not queue another analysis for a head commit that already has one.
  (Updating the existing comment and Check Run in place is verified for CI re-publishes in the smoke, not
  for a second `analyze` of an unchanged commit.)

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `409 GITHUB_APP_NOT_CONFIGURED` from connect/analyze | `GITHUB_APP_ID` / key missing in the **api** container | Set them in `.env`, `make dev` again; run the `exec api` check in step 4. |
| `403 GITHUB_APP_AUTH_FAILED` (GitHub HTTP 401) | Wrong App ID, key from another App or a revoked key, or the clock is wrong | Re-copy the App ID; generate a new key; `live_check.py` reports clock skew. Windows: resync time (Settings > Time > Sync now). WSL/VMs drift after sleep. |
| live_check: "does not look like a PEM" / "could not be parsed" | Newlines lost, extra quotes, or the webhook/client secret was used | Use `GITHUB_APP_PRIVATE_KEY_PATH` with the downloaded file, or a single line with literal `\n` between lines. It must start with `-----BEGIN RSA PRIVATE KEY-----` (or `BEGIN PRIVATE KEY`). |
| `404 GITHUB_REPOSITORY_NOT_ACCESSIBLE` | Typo in `owner/name`, or the App is not installed on that repository (installation limited to other repos) | Install App > Configure > add the repository. Case does not matter, spelling does. |
| `403` "Resource not accessible by integration" in the error message | A permission is missing (most often Checks or Pull requests write), or a permission change was not accepted | Fix the permissions on the App, then accept the changes on the installation (GitHub emails the owner and shows a banner on the installation page). `live_check.py` shows which. |
| Analysis `completed` but nothing on the pull request | `GITHUB_PUBLISH_RESULTS=false`, credentials missing in the **worker**, or `checks`/`pull_requests` not writable | Run the `exec worker` check; read `docker compose logs worker` for "Could not publish GitHub Check Run or PR comment" (the message names the GitHub error). |
| Analysis stays `pending` | Worker not running | `docker compose ps`; `docker compose logs worker`. |
| Analysis `failed`, clone error | App lacks **Contents: Read**, or the repository is large/empty | Check the permission; read the worker log (token values are redacted). |
| `403 GITHUB_INSTALLATION_NOT_LINKED` | The organization has no installation yet and single-tenant development mode is off | Dev stack: use `make dev` (`RADIUS_ENV=development`) or set `RADIUS_GITHUB_DEV_SINGLE_TENANT=true`. Otherwise have the installation linked to the organization first ([INSTALLATION_BINDING](../security/INSTALLATION_BINDING.md)). |
| `409 GITHUB_INSTALLATION_MISMATCH` | The organization is already linked to a different installation (another account's), or this repository's installation belongs to another organization | One Radius organization uses one installation. Use a repository under the same account, or a different organization id. |
| Rate limit message (`GITHUB_RATE_LIMITED` / "rate limit hit") | Primary (5000/h per installation) or secondary limit | The client waits and retries within a budget; if it still fails the message says how long GitHub asks you to wait. Re-run after that. |
| `sync-pull-requests` returns the stored PRs and `meta.github = not_configured` | The API has no App credentials | Same as the first row. |
| `sync-pull-requests` skips a pull request (`meta.skipped`) | GitHub returned a shape Radius could not parse | The reason is in `meta.skipped[].reason`; the dashboard lists it under the sync banner. |
| Poller never queues anything | `RADIUS_GITHUB_POLL_INTERVAL_SECONDS` is 0 or unset in the **worker**, or no App credentials there | `docker compose logs worker`: look for `poller enabled` / `poll_disabled` and the `poll tick finished` lines. |
| Check Run link goes to `localhost:3000` | `DASHBOARD_BASE_URL` default | Expected for a local demo; set it to a reachable URL if you show the PR on another machine. |

## 10. Limits (read before the demo)

- Analyses start when you press Analyze / Sync (or call the routes), or, with
  `RADIUS_GITHUB_POLL_INTERVAL_SECONDS` set, within one poll interval of a new commit. Without the poller
  a new commit is not picked up until you ask. The poll interval is the latency: it is not instant like a
  webhook.
- The poller only sees repositories connected through Radius (dashboard or `connect-github`) whose
  organization has an active installation id.
- `sync-pull-requests` reads only the first 100 open pull requests and does not analyze drafts.
- One Radius organization maps to one GitHub installation, and one installation to one organization.
- Verified only against a fake GitHub (see the status line). Real-GitHub behaviours the fake cannot
  show: secondary rate limits, organization SSO enforcement, renamed repositories, differences in
  GitHub's JSON for unusual pull requests.
- This is the alpha Verdict v2 path; read [../verdict-v2.md](../verdict-v2.md) before presenting its
  output as a result.
