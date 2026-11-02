# GitHub Action: upload CI test results to Radius

`actions/upload-results` is a composite action that sends the JUnit XML your tests already produce to Radius, bound to the pull request head commit. Verdict v2 uses it as execution evidence, and a successful upload enqueues a republish of the verdict (when `RADIUS_FEATURE_VERDICT_V2` is not `off`).

It is deliberately conservative: by default it **never fails your CI**, it uses no third-party actions, and it sends the minimum needed (see [What leaves the runner](#what-leaves-the-runner)).

This is separate from `.github/actions/radius-verify` (plan, upload and gate with exit codes, see [CI_INTEGRATION_GUIDE.md](../CI_INTEGRATION_GUIDE.md)). Use `upload-results` when you simply want your existing test job to contribute evidence.

## Quick start

Add the step after your tests, in the same job. Create two repository secrets: `RADIUS_API_KEY` (an API key with the `ci-upload` scope) and `RADIUS_ORG_ID`, plus the variable or secret `RADIUS_API_URL`.

```yaml
name: tests
on:
  pull_request:

permissions:
  contents: read        # the action needs nothing else

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-sha> # vX.Y.Z  (pin by full SHA)
        with:
          ref: ${{ github.event.pull_request.head.sha }}   # the analysed commit, not the merge commit
      - run: pip install -r requirements.txt pytest
      - run: pytest --junitxml=junit.xml
      - name: Upload results to Radius
        if: ${{ !cancelled() }}            # also upload failing runs: failures are evidence
        uses: <owner>/Radius/actions/upload-results@<full-sha> # vX.Y.Z
        with:
          api-url: ${{ vars.RADIUS_API_URL }}
          organization-id: ${{ secrets.RADIUS_ORG_ID }}
          api-key: ${{ secrets.RADIUS_API_KEY }}
          junit-path: junit.xml
```

Pin the action by full commit SHA with a version comment. This repository does not publish a tag for it yet (distribution is tracked as PRD-32), so pin the SHA of the Radius release you use, or vendor the `actions/upload-results` directory.

### Producing JUnit XML

```yaml
# pytest
- run: pytest --junitxml=junit.xml

# jest (npm i -D jest-junit)
- run: npx jest --ci --reporters=default --reporters=jest-junit
  env:
    JEST_JUNIT_OUTPUT_DIR: reports
    JEST_JUNIT_ADD_FILE_ATTRIBUTE: "true"   # lets Radius map cases to test files
# then: junit-path: reports/junit.xml

# vitest
- run: npx vitest run --reporter=junit --outputFile=reports/junit.xml

# maven (surefire writes XML itself)
- run: mvn -B test
# then: junit-path: target/surefire-reports/TEST-*.xml
```

Radius attributes each `<testcase>` to a test file through its `file` attribute or `classname`; reports without per-test entries cannot become evidence (see the evidence rules in the CI guide).

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `api-url` | required | Radius API base URL (`https://`; `http://` only for localhost). |
| `organization-id` | required | Radius organization UUID. |
| `api-key` | empty | Pass from a secret. Empty means "skip" (see forks). |
| `junit-path` | `junit.xml` | Glob(s), one per line or comma separated. `**` works. Matched relative to the workspace; files outside it are ignored. |
| `coverage-path` | empty | Optional Cobertura XML glob. Only the total `line-rate` is sent, as a percentage. |
| `analysis-id` | empty | Skip the lookup and use this analysis. |
| `repository`, `pull-request`, `commit-sha` | from the PR event | Used for the lookup `GET /api/v1/analyses/lookup`. `commit-sha` must be the PR **head** SHA. |
| `fail-on-upload-error` | `false` | `true` makes upload problems fail the step. |
| `include-failure-details` | `false` | `true` uploads reports unmodified (see below). |
| `max-file-size-mb` | `10` | Larger files are skipped with a warning. At most 64 files are uploaded. |
| `wait-seconds` | `120` | How long to wait for Radius to create the analysis for the commit (polling every 5s on 404). |
| `dashboard-url` | empty | If set, the summary and `analysis-url` output link to `<dashboard-url>/analyses/<id>`. |

Outputs: `status` (`uploaded`, `partial`, `failed`, `skipped-fork`, `skipped-no-secret`, `skipped-no-results`), `analysis-id`, `analysis-url`, `uploaded-count`, `skipped-count`, `verification-status`. A summary is also written to the job summary page.

## Behaviour

- **Retries.** Network errors, `429` and `500/502/503/504` are retried up to 4 attempts. `429` honors `Retry-After` (capped at 60s); otherwise backoff is 2s, 4s, 8s. Other `4xx` responses are not retried. Repeating an identical upload is idempotent server-side.
- **Never breaks CI by default.** Every problem (missing results, API errors, even an unexpected exception inside the script) becomes a `::warning` and the step exits 0. With `fail-on-upload-error: true` problems become `::error` and the step exits 1. "No results found" and "fork / no secret" never fail either way, because they are not upload errors.
- **Forks and missing secrets.** On a `pull_request` from a fork GitHub gives the workflow no secrets, so the action prints a notice and skips (`skipped-fork`); Dependabot runs or an unset secret end as `skipped-no-secret`. Do not switch to `pull_request_target` to work around this: it would run untrusted code with your secrets. The verdict for fork PRs stays `insufficient_evidence` until a maintainer re-runs the tests from a branch in the repository.
- **Malformed or non-JUnit XML is skipped, not uploaded.** The server would reject it with `422` and store nothing, so the action validates locally, warns, and counts it in `skipped-count`. Files containing a DOCTYPE or ENTITY declaration are refused for the same reason.
- **Secret handling.** The key is read from the environment (never argv), registered with `::add-mask::`, sent only in the `X-Radius-API-Key` header, redirects are refused so it cannot be forwarded elsewhere, and any server message that echoes it is scrubbed.
- **No unverifiable pins.** The action contains no `uses:` steps; it runs `python3` (3.10 or newer, preinstalled on GitHub-hosted runners) with the standard library only. `scripts/ci/check_action_pins.py` scans `actions/**/action.yml` and fails on any unpinned `uses:`.

## What leaves the runner

Only test result files you point `junit-path` / `coverage-path` at, and nothing else (no source code, no repository checkout, no environment variables, no artifacts).

By default each JUnit file is **reduced before upload** to this allow-list:

- `testsuites` / `testsuite`: name, counts (tests, failures, errors, skipped, disabled), time, timestamp, file
- `testcase`: name, classname, file, time (these are the file names and test ids)
- `failure` / `error`: element and `type` only; `skipped`: element only

Dropped: failure messages and stack traces (they can contain source lines), `system-out` / `system-err`, `properties` (can contain environment values), hostnames and every other attribute. Set `include-failure-details: true` to send the original file unchanged; then anything your test framework wrote into it, including traceback source lines, is sent.

Coverage: only the aggregate line percentage, plus the analysis id, in a small JSON body (`framework`, `coverage_percent`). Per-file coverage is not sent.

Also sent in the request: your organization id and API key (headers), the repository name, PR number and head SHA (for the lookup).

## Rollout: shadow first

1. In Radius, set `RADIUS_FEATURE_VERDICT_V2=shadow` on the API and worker. Verdict v2 is computed and stored but not published; v1 behaviour is unchanged.
2. Add this action to one repository. Open a PR and confirm the job summary shows `uploaded` and an analysis link.
3. Compare the stored v2 verdict (`GET /api/v1/analyses/{id}/verdict-v2`, or the dashboard panel) with the v1 result over a few PRs. Check that evidence appears for the tests you expect.
4. When satisfied, set `RADIUS_FEATURE_VERDICT_V2=on` so the republish after upload updates the check. Keep `fail-on-upload-error` at `false` until the setup has been stable for a while.

See [verdict-v2.md](../verdict-v2.md) for the flag semantics.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `skipped-fork` notice | PR from a fork; no secrets available. Expected. |
| `skipped-no-secret` | `RADIUS_API_KEY` not set for this event (Dependabot has a separate secrets store), or the secret name is wrong. |
| `No JUnit XML files matched` | The test step did not write a report, wrote it elsewhere, or the glob is relative to a different directory. Remember `if: !cancelled()` so a failing test step still uploads. |
| `HTTP 401` | Wrong or revoked key. |
| `HTTP 403 ... ci-upload` | The key lacks the `ci-upload` scope or belongs to another organization. |
| `HTTP 404` after waiting | No analysis for this PR head commit: the Radius GitHub App is not installed on the repo, the analysis has not run, or you checked out the merge commit; set `commit-sha` to the PR head SHA. Raise `wait-seconds` if analyses are slow. |
| `HTTP 409` | The commit differs from the analysed head, the PR has a newer analysis (push race), or the analysis failed. Re-run after the new analysis completes. |
| `HTTP 422` | Radius rejected the report (not JUnit, aggregate-only, negative counts). |
| Uploaded but verdict still `insufficient_evidence` | The report has no per-test entries for the selected test files (add the `file` attribute, see jest above), or Radius selected tests that did not run. |
| Skipped by size | Raise `max-file-size-mb` (the server also enforces its own body limit). |
