# CI Checks and Measured Baselines (F-13 / QS-05)

Baselines below were measured on 2026-11-02 against `origin/develop` (7068046)
on a developer machine (Windows 11, Python 3.12.10, Docker 29.7.2). They were
not measured on GitHub-hosted runners; CI results can differ slightly.

## Workflows

| Workflow | Job (check name) | Blocking | Purpose |
| --- | --- | --- | --- |
| `ci.yml` | `Validate` | yes (required check; name unchanged) | lint, typecheck, tests, build, migrations |
| `coverage.yml` | `Python coverage` | yes | pytest-cov with `--cov-fail-under` |
| `security.yml` | `Secret scan (gitleaks)` | yes | full git history scan |
| `security.yml` | `Dependency audit (Python)` | yes | `pip-audit`, baseline is 0 vulnerabilities |
| `security.yml` | `Dependency audit (pnpm)` | yes, against expiring baseline | `pnpm audit` gated by `.github/security/audit-baseline.json` |
| `security.yml` | `SBOM and license report` | yes for AGPL/SSPL/GPL only | CycloneDX SBOM + license reports as artifacts |
| `smoke.yml` | `Smoke (API + worker + PostgreSQL)` | after one green run on develop | end-to-end smoke of the real API, worker and PostgreSQL with a fake GitHub edge |
| `stack.yml` | `Stack boot + browser (verdict v2 off)`, `(verdict v2 on)` | after one green run on develop | boots the real Docker Compose stack and drives the dashboard in a browser |
| `nightly.yml` | `Benchmarks (non-blocking)` | never | nightly `pytest benchmarks`, JUnit artifact |

Only `Validate` is a required check today. Add the new checks to branch
protection (`docs/github-branch-protection.md`) after they have run green once.

Hardening applied to every workflow: least-privilege `permissions: contents:
read`; `concurrency` (cancel superseded PR runs, never cancel runs on
`develop`/`dev`/`main`); pip and pnpm caching; actions pinned to full commit
SHAs (the release tag is in the trailing comment). `.github/dependabot.yml`
proposes weekly updates for Actions, pip and npm.

### Pinned action versions

SHAs were read from the upstream tag refs with `git ls-remote` on 2026-11-02:
`actions/checkout` v4.4.0, `actions/setup-python` v5.6.0, `actions/setup-node`
v4.4.0, `pnpm/action-setup` v4.4.0 (peeled commit of the annotated tag),
`actions/upload-artifact` v4.6.2. gitleaks runs from the container image
`ghcr.io/gitleaks/gitleaks` v8.24.3 pinned by digest.

## Supply-chain checks (PRD-07)

| Workflow | Check name | Triggers | Recommendation |
| --- | --- | --- | --- |
| `codeql.yml` | `Analyze (python)`, `Analyze (javascript-typescript)` | PR, push (develop/dev/main), weekly Tue, manual | Require both after the first green run on develop |
| `dependency-review.yml` | `Dependency review` | PR only | Require after first green run (it only appears on PRs) |
| `scorecard.yml` | `Scorecard analysis` | push (develop/main), `branch_protection_rule`, weekly Wed, manual | Advisory, never required (it scores the repo, not the PR) |

All three use `permissions: read-all` at top level with per-job elevation
(`security-events: write` for CodeQL/Scorecard SARIF, `id-token: write` for
Scorecard publishing, `pull-requests: write` only for the dependency-review
summary comment). Every `uses:` is pinned to a full SHA; versions: 
`github/codeql-action` v4.39.1, `ossf/scorecard-action` v2.4.3,
`actions/dependency-review-action` v4.9.0 (peeled commit SHAs from
`git ls-remote` on the upstream repos, 2026-11-02).
`scripts/ci/check_action_pins.py` (run by `tests/test_workflow_action_pins.py`)
fails if any workflow `uses:` is not SHA-pinned or lacks a version comment.

### CodeQL

- Languages: `python`, `javascript-typescript` with `build-mode: none` (supported for both).
- Query suite: `security-extended`. `security-and-quality` adds maintainability findings that ruff/eslint already cover; the extended security suite keeps alerts actionable.
- `paths-ignore`: `benchmarks/**`, `tests/security/**` (prompt-injection corpus), `packages/testing/tests/test_sandbox_adversarial.py`. These contain intentionally hostile payloads. Ordinary unit tests are still scanned.
- Triage: Security tab > Code scanning. Fix, or dismiss with a reason ("false positive", "used in tests", "won't fix") and a comment; never dismiss without one. New alerts on a PR show as annotations.
- Requires "Code scanning" to be available (free on public repos; GitHub Code Security on private repos). Until enabled, SARIF upload fails with a clear error.

### Dependency review

- Fails a PR that adds or bumps a dependency with a known vulnerability of severity high or above, or with a denied license. Needs the Dependency graph (always on for public repos).
- Denied (mirrors `scripts/ci/license_check.py`): AGPL, SSPL, GPL (all SPDX variants). Allowed and not listed: LGPL (`psycopg`, the transitive `sharp` libvips dependency) and MPL-2.0.
- Fork PRs cannot comment (read-only token); the report is in the job summary. Same-repo PRs get a comment only on failure.
- Complements `security.yml` (`pip-audit`, `pnpm audit`, which cover the whole tree rather than the diff).

### Scorecard

- Runs OpenSSF Scorecard, uploads SARIF to code scanning (category `scorecard`) and as an artifact; findings appear as code scanning alerts.
- Publishing (badge, api.securityscorecards.dev) requires a public repository; the job sets `publish_results` from `repository.private == false`, and prints a notice when not public.
- The Branch-Protection check needs a token that can read branch protection. The default `GITHUB_TOKEN` cannot, so that check is incomplete (lower or "?") until the owner adds a repository secret named `SCORECARD_TOKEN` (fine-grained PAT with read-only "Administration" on this repo, or classic `repo` scope; see the scorecard-action docs). The workflow does not require the secret: it falls back to the default token and logs a notice.
- Triage: low scores on Branch-Protection, Code-Review, Maintained and Fuzzing are expected for a young repo and tracked in `docs/production-readiness`. Pinned-Dependencies is guarded by the pin test above. Dockerfile pinning is PRD-08.
- Baseline score: not recorded. It can only be measured after the first run on GitHub; record it in `docs/production-readiness/SCORECARD_BASELINE.md` afterwards. Local run (optional): `docker run --rm -e GITHUB_AUTH_TOKEN=$TOKEN gcr.io/openssf/scorecard:stable --repo=github.com/OWNER/REPO`.

### Dependabot

`.github/dependabot.yml`: weekly (Monday 05:00 UTC) updates for GitHub Actions, pip, npm (pnpm workspace), docker (`apps/api`, `apps/worker`, `apps/dashboard`) and docker-compose. Minor/patch updates are grouped per ecosystem; majors arrive as individual PRs, except semver-major updates of `next`, `react`, `react-dom`, `@types/react`, `@types/react-dom`, `typescript`, `eslint` and `eslint-config-next`, which are ignored (handled in planned upgrade tasks; security updates still apply). The pip ecosystem uses `versioning-strategy: increase-if-necessary` so lower bounds are only raised when required. PR limits 5 (3 for compose). Commit prefixes: `ci(deps)` for Actions, `build(deps)` / `build(deps-dev)` otherwise. No `labels:` are set because the label set is created by PRD-04. Dependabot alerts and security updates must be enabled in repository settings (separate from this file).

### Run locally

```bash
python -m pytest tests/test_workflow_action_pins.py -q      # SHA-pin guard
python scripts/ci/check_action_pins.py
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint@sha256:887a259a5a534f3c4f36cb02dca341673c6089431057242cdc931e9f133147e9   # actionlint 1.7.7
# CodeQL CLI (optional): codeql database create --language=python db && codeql database analyze db codeql/python-queries:codeql-suites/python-security-extended.qls
```

### Branch protection recommendation (not applied here)

After one green run on develop: require `Analyze (python)`, `Analyze (javascript-typescript)` and `Dependency review` alongside `Validate`. Keep Scorecard advisory. Owner applies via `docs/github-branch-protection.md`.

### Owner actions

1. Enable Code scanning, Dependency graph, Dependabot alerts and security updates (Settings > Code security).
2. Optionally add secret `SCORECARD_TOKEN` (see above).
3. After merge, check first runs of all three workflows and record the Scorecard baseline.

### Verification status

Verified locally: actionlint 1.7.7 clean on all workflows, YAML parse of `dependabot.yml`, pin guard test, ruff. Not verifiable until GitHub runs them: CodeQL extraction results and run time, `config:` `paths-ignore` taking effect, `deny-licenses` handling of compound SPDX expressions, Scorecard publish and SARIF upload, Dependabot schema acceptance (Dependabot reports config errors in Insights > Dependency graph > Dependabot).

## End-to-end smoke

- Workflow: `smoke.yml` (pull requests and pushes to `develop`; `contents: read`, no secrets, 15 minute timeout, `postgres:16-alpine` service like `coverage.yml`). It runs `python scripts/smoke_e2e.py`, which takes about 15 s after dependency installation.
- Local run: `docker compose up -d postgres`, then `DATABASE_URL=postgresql+psycopg://radius:radius@localhost:5432/radius python scripts/smoke_e2e.py`. `tests/test_smoke_e2e.py` wraps it for pytest and is skipped unless `RADIUS_SMOKE=1` and `DATABASE_URL` is PostgreSQL, so `coverage.yml` and local runs without Postgres skip it.
- Proves: migrations, health/readiness, auth and scope enforcement, signed webhook to analysis, worker loop, Verdict v2 verdict, renderer output (alpha disclaimer, v2 marker) and republish after CI results, all against real code and a real database. See "End-to-end smoke test" in `docs/DEVELOPMENT_GUIDE.md`.
- Does not prove: real GitHub behaviour (the GitHub REST API is an in-memory fake), a browser or the dashboard, Docker image builds or Compose wiring, the test sandbox.
- Dashboard: the Next.js dashboard is not started by the smoke. Its lint, typecheck, test and build already run in the `Validate` job of `ci.yml` (`pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`), so no extra pnpm step was added; a browser-level smoke remains a follow-up.
- Status: the first run on a CI runner has not happened yet; it was run locally against `postgres:16-alpine` only.

## Stack boot and browser end-to-end

- Workflow: `stack.yml`, job `stack`, two matrix legs: `RADIUS_FEATURE_VERDICT_V2=off` and `on` (the `on` leg exercises the Verdict v2 import path in the API and the worker). Pull requests and pushes to `develop`; `contents: read`, no secrets, 25 minute timeout, actions pinned by SHA.
- Steps: `python3 scripts/gen_dev_env.py` (random local-dev `.env`), `docker compose config -q`, build of the `api`, `worker`, `migrations` and `dashboard` images with `docker-compose.yml` plus `docker-compose.dev.yml`, `up -d --wait --wait-timeout 300`, then `scripts/ci/check_stack.py`, then the Playwright suite in `e2e/`. Container logs are dumped and uploaded when a step fails; `down -v` always runs.
- `scripts/ci/check_stack.py` (pure parts unit-tested in `tests/test_check_stack.py`): after a 60 s stability window every long-running service (`postgres`, `api`, `worker`, `dashboard`) must still be `running` (and `healthy` where it has a health check), `migrations` must have exited 0, `GET /api/v1/health`, `/api/v1/ready`, dashboard `/` (after the redirect to sign-in) and `/login` must return 200, and the worker log must contain `Radius worker ready`. This is what catches an image that crashes on import (for example `No module named radius_evidence` when a Dockerfile `PYTHONPATH` misses a package) or a crash loop.
- Browser tests: `e2e/` is a separate npm project (its own pinned `package-lock.json`, installed with `npm ci`; the pnpm workspace and `pnpm-lock.yaml` are untouched). `@playwright/test` 1.64.1 with the Playwright-managed Chromium (`npx playwright install --with-deps chromium`). `e2e/tests/dashboard.spec.mjs` signs up (dev auto-verify), must land on the dashboard and must not show "Check your email", waits for the home page to become network-idle, opens `/pull-requests`, `/repositories`, `/analyses`, `/settings`, `/help`, signs out and signs in again. It fails on page errors, `console.error` and any HTTP 4xx/5xx response except the documented one (`GET /api/v1/auth/me` -> 401, the session probe before sign-in and after sign-out). Screenshots, the HTML report and failure traces are uploaded as the artifact `e2e-verdict-v2-<off|on>`. The base URL must be `localhost` (the session cookie is host-scoped).
- Local run against a running dev stack: `cd e2e && npm ci && npx playwright install chromium && npx playwright test` (set `E2E_CHROME_PATH` to use an installed Chrome instead).
- Does not prove: real GitHub behaviour, the sandbox profile, the production-like compose file (this uses the dev override: `RADIUS_ENV=development`, auto-verified sign-ups), cross-browser behaviour (Chromium only). No buildx layer cache is used, so each leg builds the images from scratch.
- Status: the workflow has not run on a CI runner yet. Verified locally: `actionlint` 1.7.7 clean, `scripts/ci/check_action_pins.py`, `docker compose config -q` with a generated `.env`, the unit tests, and the browser spec against an already running local dev stack (installed Chrome). The first real run is in CI. Note: the `worker` and `api` images need the `radius_evidence` package on `PYTHONPATH`; until that Dockerfile fix is on the branch under test, this job is expected to fail on the worker ready line.

## Coverage

- Command: `python -m pytest apps/api/tests apps/worker/tests packages/*/tests tests --cov` (config in `pyproject.toml` `[tool.coverage]`: sources `apps`, `packages`; tests, conftest and the dashboard are omitted; line coverage).
- Measured baseline: **86%** total (8406 statements, 1160 missed). 457 passed, 5 skipped, 4 failed locally; the 4 failures are Windows/Docker environment tests (`test_sandbox_runner.py` x3, `test_subprocess_runner.py` x1) that should pass on the Linux runner, which would raise the number.
- Threshold: **83%** (`COVERAGE_MIN` in `coverage.yml`), 3 points below baseline to avoid flakiness. Raise it once the first CI run shows the real number; never lower it.
- The JS dashboard has no coverage measurement yet (follow-up).

## Secret scanning

- Config: `.gitleaks.toml` (extends the default rules). The only allowlist entries are four exact fake values in test fixtures, verified by reading each hit: `ghs_FAKEinstallationTOKEN...` (`apps/worker/tests/test_failure_handling.py`), `ghs_abcdefghijklmnopqrstuvwxyz0123456789` and the `MIIEbody{TOKEN}` private-key placeholder (`packages/shared/tests/test_redaction.py`, `packages/analysis/tests/test_sqlalchemy_job_queue.py`), and `e2e-secret-api-key-0123456789` (`tests/test_radius_ci_e2e.py`). `.env.example` produced no findings, so it is not allowlisted.
- Baseline (gitleaks v8.24.3, all refs of a mirror clone of the main repo, 69 commits scanned): without the allowlist 5 findings, all fake test fixtures; **with `.gitleaks.toml`: 0 findings**.
- A seeded fake AWS key and GitHub token in a scratch directory were detected (exit code 1), confirming the scanner fails on a secret.
- Full-history scan (also run by the `secrets` job, which uses `fetch-depth: 0`). Locally, from a normal clone:

  ```bash
  docker run --rm -v "$PWD:/repo:ro" ghcr.io/gitleaks/gitleaks@sha256:e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055 \
    git /repo --config /repo/.gitleaks.toml --redact --no-banner --exit-code 1
  ```

  (From a linked git worktree the container cannot resolve the `.git` file; scan a `git clone --mirror` instead.) Run this before making the repository public (F-03).

## Dependency audit

- Python: `pip-audit 2.10.1` over the frozen environment (125 packages): **0 known vulnerabilities**. The job is therefore strictly blocking with no baseline file.
- Node: `pnpm audit` (pnpm 9.15.0). On 2026-11-02 the initial baseline held 22 unique advisories (3 critical, 16 high, 8 moderate). After the upgrade below the audit reports **0 critical, 0 high, 0 low and 1 moderate** (`minimatch` 3.1.5, ESLint tooling, see baseline). The baseline file now contains only that moderate entry (added 2026-11-02, expires 2027-01-31).

  | Advisory | Package (severity) | Fix | How |
  | --- | --- | --- | --- |
  | GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r | next (critical, high) | next 15.5.28 | direct bump `^15.5.28` (also `eslint-config-next`) |
  | GHSA-2xp9-vwfh-vxw4, GHSA-p293-qw3h-jr36 | next (critical) | next >= 15.5.24 | same bump |
  | GHSA-4jqv-mc3x-m676, GHSA-mcj8-r9mp-w47p | next (moderate) | next >= 15.5.27 | same bump |
  | GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849, GHSA-fxqj-rqcc-2cmp, GHSA-qx2v-qp2m-jg93 | postcss (high/moderate) | postcss 8.5.32 (>= 8.5.23) | override `postcss@<8.5.23`; `next` pins 8.4.31 exactly and no 15.x release moves it |
  | GHSA-2v37-7h3g-55p8 | nanoid (high) | nanoid 3.3.20 (>= 3.3.18) | override (transitive of postcss) |
  | GHSA-68fv-2mgg-jv7q | source-map-js (high) | 1.2.2 | override (transitive of postcss) |
  | GHSA-f88m-g3jw-g9cj, GHSA-rgj7-g3m4-5g8c, GHSA-wq5f-xc86-pv6w | sharp (high) | sharp 0.35.5 | override `sharp@<0.35.5`; next 15.5.28 declares `^0.34.3 \|\| ^0.35.5` so this is within its range |
  | GHSA-2883-xcg3-v3hh, GHSA-5p4m-2wfm-xmqj | js-yaml (high) | 4.3.2 | override (via `@eslint/eslintrc`) |
  | GHSA-6j4f-fj2g-mc7p, GHSA-qhr7-859c-m2p7, GHSA-rgw5-rvv9-x895, GHSA-q2hr-2g5m-vwhr | brace-expansion (high/moderate) | 1.1.21 and 5.0.12 | overrides for the 1.x and 4-5.x lines |
  | GHSA-g3hv-75wg-m249 | minimatch (moderate) | 11.0.1 for the 10.x copy (override); the 3.x copy stays | 11.x has no CommonJS default export, so forcing it on `@eslint/eslintrc` breaks `eslint .` (verified); baselined |

  Overrides live in the root `package.json` under `pnpm.overrides`. Remove each one when its parent releases a patched dependency range. The Next.js 16 bump proposed by Dependabot (16.4.3) was not needed: a patched 15.x line exists, so no major was taken.
- Gate (`scripts/ci/audit_gate.py`): fails on any high/critical advisory not in the baseline, and fails on any baseline entry past its expiry (checked with `--today 2027-02-01`: exit 1). Moderate/low are reported only. Remove entries as they are fixed; do not extend an expiry without a written reason. The baseline is now near-empty. For a new advisory: upgrade to the first patched version (direct bump, or a `pnpm.overrides` entry for transitive dev tooling), re-run `pnpm audit --json > pnpm-audit.json && python scripts/ci/audit_gate.py pnpm-audit.json .github/security/audit-baseline.json`, and only baseline it (id, justification, expiry) when no patched release exists or the fix breaks the build. Because entries expire, the job turns red on the expiry date by design.
- Container image scanning (Trivy), mentioned in QS-05, is not included; see follow-ups.

## SBOM and licenses

- `cyclonedx-py environment` produces a CycloneDX 1.6 JSON SBOM of the Python environment (127 components locally), uploaded as the `sbom-and-licenses` artifact with the license reports (90-day retention).
- Python licenses (125 packages) are mostly MIT/BSD/Apache-2.0; weak copyleft: `psycopg` and `psycopg-binary` (LGPL-3.0), plus MPL-2.0 packages. Node (pnpm licenses): MIT 253, Apache-2.0 18, ISC 10, BSD-2/3 9, MPL-2.0 1, plus `Apache-2.0 AND LGPL-3.0-or-later` 1 (a transitive native image dependency; confirm it is not redistributed in a way that conflicts with LGPL).
- Policy (`scripts/ci/license_check.py`): fail on AGPL, SSPL and GPL; allow LGPL/MPL (reported). Current result: ok. This is an engineering policy, not legal advice; confirm with counsel before distribution.

## What was executed versus only syntax-checked

Executed locally (real numbers above): pytest with coverage, `pip-audit`, `pnpm audit`, `pnpm licenses list`, `pip-licenses`, `cyclonedx-py`, gitleaks (history and directory, with and without config, plus a seeded secret), `audit_gate.py` and `license_check.py`.

Only syntax/lint-checked: all workflow files (`actionlint` 1.7.7 via Docker, clean, including shellcheck of `run:` blocks). The workflows themselves have **not** run on GitHub Actions. Unverified until the first run: the gitleaks container invocation with `--entrypoint /bin/sh`, runner-side coverage percentage, `pnpm licenses list --json` output on the runner, and the nightly benchmark job (locally `benchmarks/test_benchmarks.py::test_confidence_scoring_completeness_and_verification_status` failed in the Windows environment).

## Demonstration PRs (F-13 acceptance, still to do)

F-13 asks that CI fail on a seeded secret, a vulnerable dependency and a coverage drop. Open three throwaway PRs on GitHub to demonstrate and record links here: (1) add a fake `AKIA...` key, (2) pin a known-vulnerable package, (3) delete tests to drop coverage under 83%.

## Placeholder

`ci.yml` contains a commented placeholder step for the F-07 adversarial sandbox suite; enable it in the `Validate` job once that suite exists.
