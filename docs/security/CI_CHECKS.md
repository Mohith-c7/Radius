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
- Node: `pnpm audit` (pnpm 9.15.0, 380 dependencies): **27 advisory records (22 unique advisories): 3 critical, 16 high, 8 moderate** (affecting `next`, `postcss`, `sharp`, `brace-expansion`, `js-yaml`, `nanoid`, `source-map-js`, `minimatch`). These are real and untriaged, so they are recorded in `.github/security/audit-baseline.json` with `added: 2026-11-02` and `expires: 2027-01-31`.
- Gate (`scripts/ci/audit_gate.py`): fails on any high/critical advisory not in the baseline, and fails on any baseline entry past its expiry (checked with `--today 2027-02-01`: exit 1). Moderate/low are reported only. Remove entries as they are fixed; do not extend an expiry without a written reason. Because the baseline expires, the job will turn red on 2027-01-31 unless these are remediated, by design.
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
