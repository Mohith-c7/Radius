# Demo runbook: Radius on real pull requests (about 10 minutes)

A rehearsed script for showing Radius on a real GitHub repository from a laptop. It uses three
scripted pull requests whose outcomes are different on purpose, and uploads CI results from the
laptop because a GitHub-hosted runner cannot reach an API running on it.

**Honest status.** Everything here was exercised against a fake GitHub (`scripts/demo_verify.py`,
section 8). Nobody has run it against `api.github.com` yet, and the dashboard pages were not
re-checked for this runbook. GitHub settings-page labels come from
[operations/LIVE_GITHUB_DEMO.md](operations/LIVE_GITHUB_DEMO.md) (pull-based flow, PR #122; read it
for the GitHub App setup and the troubleshooting table). Rehearse once on the real repository
before presenting, and keep section 7 (the fallback) ready.

What the three pull requests show (expected outcomes in [`demo/EXPECTED.md`](../demo/EXPECTED.md)):

| PR | Story | Result after CI results |
| --- | --- | --- |
| A `demo/a-strong-tests` | correct change, exact-value and boundary tests | **Supported by static evidence (alpha)**, rule R4 |
| B `demo/b-weak-tests` | correct change, CI green, tests only check truthiness | **Not verified: insufficient evidence**, rule R2b |
| C `demo/c-tampered-tests` | validation removed, tests weakened, deleted, skipped, CI green | **Failed**, rule R1c; Check Run conclusion `failure` |

The point of the demo is B and C: green CI is not evidence. A is the contrast.

## 0. Prerequisites (do these the day before)

* Docker, Python 3.12 with `uv`, `git`, a browser. Windows: use Git Bash for the commands below.
* A GitHub App with the webhook **off**, installed on one empty throw-away repository you own, and
  its private key stored outside the checkout. Follow sections 1 to 3 of
  [operations/LIVE_GITHUB_DEMO.md](operations/LIVE_GITHUB_DEMO.md).
* `.env` (from `make env`) with `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (single line),
  `GITHUB_PUBLISH_RESULTS=true`, `RADIUS_FEATURE_VERDICT_V2=on`,
  `RADIUS_FEATURE_INTENT_INGESTION=true`, `RADIUS_INTENT_EXTRACTION_MODE=sections` (the default in
  `.env.example`) and `DASHBOARD_BASE_URL=http://localhost:3000`.
* **`DASHBOARD_BASE_URL` is the address the "details" link in the Check Run and PR comment points
  to** (`<DASHBOARD_BASE_URL>/analyses/<analysis id>`). `http://localhost:3000` opens only on this
  laptop, which is right when you share your screen. For anyone else, set a reachable `http(s)` URL
  and restart the worker. An unset or non-http value gives no link at all (not a broken one).
* Never put a token or key in the demo repository, in a chat, or in the terminal history you share.

## 1. Build the demo repository (once, before the demo)

```bash
python scripts/demo_repo.py --out ~/radius-demo-out --repo YOUR-USER/radius-demo-test
```

It writes `~/radius-demo-out/work` (a git repository: `main`, three `demo/*-base` branches, three PR
branches), a bare copy, `PR_BODIES.md` (titles and bodies) and prints the exact git commands. It never
pushes and never reads a token. The result is deterministic: the same commit ids on every run. Run
the printed commands yourself, authenticating the way you normally do:

```bash
cd ~/radius-demo-out/work
git remote add origin https://github.com/YOUR-USER/radius-demo-test.git
git push -u origin main demo/a-base demo/b-base demo/c-base \
    demo/a-strong-tests demo/b-weak-tests demo/c-tampered-tests
```

Then, in the GitHub UI (or with whatever tool you use), open **three pull requests**, each from the
scenario branch **into its own base branch** (A: `demo/a-strong-tests` into `demo/a-base`, B and C
likewise). Use the titles and bodies from `PR_BODIES.md`. Why separate bases: Radius judges a pull
request against every criterion in the base branch's `.radius/intent.yml`. With all three modules'
criteria on one base, PR A could not become verified (observed). Note the three PR numbers.

## 2. Start the stack and check GitHub (before you start talking)

```bash
make dev        # or: .\scripts\dev.ps1 dev
python scripts/live_check.py   # with GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, RADIUS_LIVE_REPO set
```

`live_check.py` is read-only and must end without FAIL. Open `http://localhost:3000` in a tab.

Shell variables used below (the key comes from `.env`; do not echo it):

```bash
export RADIUS_API_URL=http://localhost:8000
export RADIUS_ORG_ID=00000000-0000-4000-8000-000000000001
export RADIUS_API_KEY="$(grep '^RADIUS_API_KEY=' .env | cut -d= -f2-)"
export API=$RADIUS_API_URL/api/v1
export H1="X-Radius-Organization-Id: $RADIUS_ORG_ID"; export H2="X-Radius-API-Key: $RADIUS_API_KEY"
```

## 3. Connect and analyze (minutes 0 to 3)

```bash
curl -s -X POST "$API/repositories/connect-github" -H "$H1" -H "$H2" \
     -H 'Content-Type: application/json' -d '{"repository":"YOUR-USER/radius-demo-test"}'
# note data.id = REPO_ID
for n in <PR-A> <PR-B> <PR-C>; do
  curl -s -X POST "$API/repositories/$REPO_ID/pull-requests/$n/analyze" -H "$H1" -H "$H2"; echo
done
```

Wait a few seconds. Open each pull request. **What you should see (first comment):** one comment and
one Check Run named `Radius confidence`. A and B say "insufficient evidence" (Radius has no test
results yet; this is expected and honest). C already says **Failed** with a tamper findings list,
because tamper detection is static. Say this out loud: the first comment on A is not the result, the
result comes after CI.

## 4. Upload CI results from the laptop (minutes 3 to 6)

A GitHub-hosted runner cannot reach `localhost:8000`, so run the tests locally and upload the report.
The helper runs the repository's pytest suite, writes JUnit XML and uploads it bound to the commit
you have checked out (`git rev-parse HEAD`). The checked-out commit must equal the pull request head
on GitHub (that is why you pushed the branches unchanged).

```bash
export RADIUS_REPO=/path/to/your/Radius/checkout
cd ~/radius-demo-out/work
git checkout demo/a-strong-tests
python "$RADIUS_REPO/scripts/radius_ci.py" run --repository YOUR-USER/radius-demo-test --pr <PR-A>
git checkout demo/b-weak-tests
python "$RADIUS_REPO/scripts/radius_ci.py" run --repository YOUR-USER/radius-demo-test --pr <PR-B>
git checkout demo/c-tampered-tests
python "$RADIUS_REPO/scripts/radius_ci.py" run --repository YOUR-USER/radius-demo-test --pr <PR-C>
```

`--dry-run` runs the tests and shows what would be sent without any network call (use it to rehearse
without touching the stack). The API key is read from `RADIUS_API_KEY` only, is not passed to the
test process, and never printed. Errors you may meet, all with a hint printed by the script:

| Output | Meaning | Fix |
| --- | --- | --- |
| `HTTP 409` | the commit is not the analysed head, the PR has a newer head, or the analysis is not complete | `git checkout` the exact PR branch, `git pull`, re-run `analyze` for the new head |
| `HTTP 422` | the report is not JUnit with `<testcase>` entries | run from the repository root; check `pytest` works |
| `HTTP 403` | wrong key for the org, or a read-only key (uploads need write scope) | re-copy the key from `.env`; check `RADIUS_ORG_ID` |
| `HTTP 404` | repository not connected, or no analysis for that PR and commit | repeat section 3 |
| exit code 4 | the Radius verdict is `failed` (this is the expected result for PR C) | none; that is the demo |

The upload makes the worker recompute the verdict and **update the same comment and Check Run in
place** (still one of each). Refresh the pull request page (the page does not push updates).

## 5. What to point at (minutes 6 to 10)

* **PR A.** Comment headline "Supported by static evidence (alpha)"; "2 of 2 stated criteria
  supported"; the table shows support above the 0.50 threshold with "strong" assertions. The Check
  Run is `neutral`: the alpha never blocks a merge by itself. Do not call this a proof; the comment
  itself says so.
* **PR B.** Same green CI, different result: "Not verified - insufficient evidence", 0 of 2
  criteria supported. The tests only assert that something is returned. The criterion about `ValueError`
  has no test at all ("No test is linked to this criterion"). The "What to do next" list tells the
  author what test to add.
* **PR C.** "Failed", rule R1c, four tamper findings with file and test names: an exact check weakened
  to `is not None`, a self-comparison that can never fail, a deleted test, and `@pytest.mark.skip`
  added. Check Run conclusion `failure` (red). CI was green; Radius still failed it.
* **Check Run "Details" link** goes to the dashboard analysis page (`DASHBOARD_BASE_URL`). Open it
  for one pull request and show the criteria and evidence there.
* The disclaimer line at the top of each comment is deliberate: Verdict v2 is an alpha with
  uncalibrated thresholds.

## 6. Resetting for a second run

Close the pull requests, delete the remote branches, or create a fresh empty repository and repeat
section 1. A new head commit needs a new `analyze` call (there is no push trigger in this flow). The
demo repository is deterministic, so re-pushing gives the same commit ids.

## 7. Fallback if GitHub or the laptop network fails

The same three scenarios run offline against a fake GitHub, through the real services (migrations,
API, worker, Verdict v2, GitHub client) with pytest really run on each branch:

```bash
docker run -d --name radius-demo-pg -e POSTGRES_USER=radius -e POSTGRES_PASSWORD=pw \
    -e POSTGRES_DB=radius -p 127.0.0.1:55433:5432 postgres:16-alpine
export DATABASE_URL=postgresql+psycopg://radius:pw@127.0.0.1:55433/radius
uv run --frozen python scripts/demo_verify.py --show-comment      # about 1 minute
```

It prints one line per scenario (verdict before and after CI, deciding rule, Check Run conclusion)
and the full PR comment text, which is exactly what GitHub would show. Use a separate Postgres on a
free port so a running dev stack is not touched. Run it once before the demo, copy the output into
slides or a terminal recording, and present from that if live GitHub fails. `scripts/smoke_e2e.py`
is the broader rehearsal (all eight fixtures, `--all`).
With `RADIUS_SMOKE_KEEP_DB=1` the scenario databases are kept so you can point a local API and the
dashboard at one; that dashboard path was **not** tested for this runbook.

## 8. What was actually observed (fake GitHub, `scripts/demo_verify.py`)

| PR | Before CI results | After CI results | Rule | Check Run conclusion | Criteria |
| --- | --- | --- | --- | --- | --- |
| A | insufficient evidence | verified | R4 | neutral | 2 of 2 proven (S 0.74, 0.62) |
| B | insufficient evidence | insufficient evidence | R2b | neutral | 1 weak (0.28), 1 unevidenced (0.01) |
| C | failed | failed | R1c | failure | 0 of 3 supported, 4 tamper findings (T001, T002, T004, T005) |

All three match `demo/EXPECTED.md`. Real GitHub rendering, the GitHub App permissions and the
dashboard pages were not part of that run.

## 9. Troubleshooting

See the table in [operations/LIVE_GITHUB_DEMO.md](operations/LIVE_GITHUB_DEMO.md) section 8 for GitHub
and credential problems. Demo-specific:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| PR A stays "insufficient evidence" after upload | the PR targets `main` (all criteria) instead of `demo/a-base`, or no results arrived | retarget the PR to `demo/a-base`; check the upload printed a verdict |
| Upload says HTTP 409 | local `HEAD` is not the pushed PR head | `git checkout` the branch, `git pull`, `analyze` again |
| Comment does not change after upload | worker not running or page not refreshed | `docker compose ps`; read the worker log; refresh |
| Details link opens a page that does not load | `DASHBOARD_BASE_URL` is `localhost` and you are on another machine | set a reachable URL in `.env`, restart the worker; links of already published comments update on the next publish |
| `radius_ci.py` fails before uploading with "pytest exited with code" | tests could not run (import error) | run `python -m pytest` in the checkout and fix; nothing is uploaded in that case |
| A first comment is anticlimactic | expected: no CI results yet | say so, then run section 4 |
