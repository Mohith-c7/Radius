# Production-readiness backlog (PRD-xx)

Companion to [AUDIT.md](AUDIT.md). Template follows `docs/research/IMPLEMENTATION_PLAN.md` section 2 (rules in section 1 apply: branch flow, conventional commits, Definition of Done, extra rules for AI agents). Fields: Owner type, Depends on, Branch, Size, Files owned, Goal, Acceptance, Tests/verification. "Files owned" is the merge-conflict boundary: two tasks in the same wave never own the same path.

Status key: **NEW** = not in the research plan. **EXT** = extends an existing task (do not duplicate; see section 2). All tasks start `[ ]`.

**Verification note (2026-11-03).** No box was ticked on the strength of this pass. What was run: the dev Compose stack, a Chrome walk-through of sign-up, dashboard, demo data and a Verdict v2 analysis, and green develop CI, Coverage, Security, CodeQL, Smoke and Scorecard (7.4). That supports the existing ticks for PRD-07 and PRD-08 only as far as CI goes. It does not satisfy PRD-25 (timing over clean machines was not measured), PRD-17 (the production-like procedure was not run), PRD-22 (no browser e2e in CI), PRD-13, PRD-26 or PRD-30. See [KNOWN_LIMITATIONS](../KNOWN_LIMITATIONS.md) and [RELEASE_CHECKLIST](../RELEASE_CHECKLIST.md).

## 1. Waves at a glance

| Wave | Tasks | Can start | Theme |
|---|---|---|---|
| 0 human | PRD-01, PRD-02 | immediately | licence decision, GitHub settings |
| 1 hygiene | PRD-03 to PRD-09, PRD-11 | immediately, in parallel (PRD-10 after PRD-01) | community files, supply-chain CI, container hardening, API hardening |
| 2 release + docs | PRD-10, PRD-12 to PRD-19 | after named deps | release pipeline, packaging, Helm, docs site |
| 3 quality | PRD-20 to PRD-25 | after Wave 1 CI changes merge | dogfood mutation, fuzz, browser e2e + a11y, perf |
| 4 security + ops | PRD-26 to PRD-30 | parallel with Wave 3 | ASVS mapping, SSO, migrations, privacy, pen test |
| 5 ecosystem + gate | PRD-31 to PRD-36 | after Waves 2-4 | research package, distribution, badge, v1.0 gate |

## 2. Already covered by existing tasks (do not duplicate)

| Need | Existing task | PRD role |
|---|---|---|
| Licence review and choice | QS-13 | PRD-01 is the decision wrapper; implement files after |
| Threat model | QS-01 | none; PRD-27 consumes it |
| Sandbox pen test | QS-03 | PRD-30 covers whole-product external review |
| Tenant isolation tests | QS-04 | none |
| Secrets/dependency scanning | QS-05 (partly done, see `docs/security/CI_CHECKS.md`) | PRD-07/08 add SAST, image scan |
| Retention and privacy | QS-06 | PRD-29 adds legal templates |
| Load/perf tests | QS-07 | PRD-23 adds published benchmark pages on top |
| SLOs and alerts | QS-08 | none |
| Cost controls | QS-10 | none |
| Backup / DR | QS-11 | none |
| Accessibility review | QS-12 | PRD-22 adds the automated CI part |
| GitHub App polish, CLI, Action v2, MCP, hooks, plugin interface | IT-01..IT-05, IT-08 | PRD-14/32 handle publishing only |
| Public API docs and scoped keys | IT-09 | PRD-12, PRD-15 add key hashing/rotation and OpenAPI CI |
| RBAC and audit log | MG-06 | none |
| Onboarding, demo repo, docs site, design partners | PL-03, PL-04, PL-05, PL-06 | PRD-25 measures PL-03; PRD-18 supplies docs structure for PL-05 |
| Paper and datasets | EP-xx in EVALUATION_PLAN | PRD-31 packaging only |

## 3. Wave 0: human decisions (start now)

### PRD-01 Licence, contribution terms, DCO decision   [~] (c93509e: Apache-2.0 `LICENSE`, `NOTICE`, DCO contributing guide merged; second-author confirmation and institution/IP check remain, see QS-13)   (EXT of QS-13)
- Owner type: human-required
- Depends on: none
- Branch: `docs/licence-decision`
- Size: S
- Files owned: `LICENSE`, `NOTICE`, `docs/decisions.md` (append DEC entry)
- Goal: choose the licence (permissive vs copyleft vs open-core split, informed by RESEARCH_NOTES 2.2) and DCO vs CLA.
- Acceptance: LICENSE and NOTICE committed; DEC entry records the choice and rationale; `pyproject.toml`/`package.json` licence fields set by PRD-14 follow it; borrowed-code review (QS-13) signed off.
- Tests/verification: GitHub shows the detected licence; `licensee`-style detection OK **[tool not verified]**.

### PRD-02 GitHub settings as code or checklist   [ ]   NEW
- Owner type: human-required
- Depends on: none
- Branch: `docs/github-settings`
- Size: S
- Files owned: `docs/github-branch-protection.md`, `scripts/apply-github-branch-protection.ps1`
- Goal: enable private vulnerability reporting, secret scanning + push protection, Dependabot alerts, Discussions with categories, 2FA for all committers, security contact mailbox; extend branch protection to require the new checks (CodeQL, Scorecard not required, container scan, commit lint) once green.
- Acceptance: checklist in the doc with date and who verified each item; branch protection reaches Scorecard tier 3 (status checks required, PR required); no force push/deletion on develop/main.
- Tests/verification: Scorecard Branch-Protection check reads >= 6 after PRD-07 lands (tier 2-3 per source); screenshot or API output attached to the PR.

## 4. Wave 1: hygiene (parallel; disjoint files)

### PRD-03 Community health files   [x] (fdb7941)   NEW
- Owner type: pair (human supplies contact, conduct enforcement contact)
- Depends on: PRD-02 for mailbox; otherwise none (use placeholder marked TODO-human)
- Branch: `docs/community-files`
- Size: S
- Files owned: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, `GOVERNANCE.md`, `MAINTAINERS.md`, `AGENTS.md`
- Goal: the community profile set. SECURITY.md: contact, private reporting link, scope, 14-day acknowledgement target (Best Practices passing), supported-versions table, disclosure timeline, safe-harbour wording for researchers. CONTRIBUTING: dev setup from DEVELOPMENT_GUIDE, branch/commit rules, tests, DCO line if PRD-01 chose it, AI-assisted contribution policy. CODE_OF_CONDUCT: adopt a standard text (Contributor Covenant) **[text not fetched; fetch before use]**.
- Acceptance: GitHub community profile shows README, CoC, CONTRIBUTING, LICENSE (needs PRD-01), security policy; Scorecard Security-Policy >= 9 after scan.
- Tests/verification: markdown link check; a new contributor follows CONTRIBUTING on a clean clone and runs tests (record in PR).

### PRD-04 Issue forms, discussion templates, labels   [x] (731c9fa)   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `chore/issue-templates`
- Size: S
- Files owned: `.github/ISSUE_TEMPLATE/*`, `.github/DISCUSSION_TEMPLATE/*`, `.github/labels.yml`, `.github/pull_request_template.md`
- Goal: bug, feature, docs issue forms (YAML with valid front matter), `config.yml` with security link and discussions link; labels incl. `good first issue`, `help wanted`; PR template adds changelog fragment, test and docs checkboxes.
- Acceptance: GitHub shows issue templates under the community profile; forms validate.
- Tests/verification: `actionlint`-style schema check **[tool choice open]**; open a test issue in a fork.

### PRD-05 README and first-impression pass   [x] (2ab7fc7)   NEW
- Owner type: pair (screenshots/GIF need a running stack)
- Depends on: none (updates later by PRD-18, PRD-25)
- Branch: `docs/readme-overhaul`
- Size: M
- Files owned: `README.md`, `docs/assets/*`
- Goal: one-line value, screenshot/GIF of PR comment and dashboard, quickstart using `docker compose` (10-minute target), status/maturity statement (pre-1.0), badges (CI, Scorecard, Best Practices once available, licence), links to docs, honesty section kept.
- Acceptance: quickstart commands copy-paste verified on a clean machine; no claim without a linked evidence file; no "best"/"guaranteed" wording.
- Tests/verification: link check; PRD-25 harness later automates the quickstart.

### PRD-06 Changelog and commit lint   [x] (9a41ece)   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `chore/changelog-commitlint`
- Size: S
- Files owned: `CHANGELOG.md`, `changelog.d/README.md`, `.github/workflows/commit-lint.yml`, `docs/RELEASING.md`
- Goal: Keep-a-Changelog file with Unreleased; fragment directory (pattern used by semgrep and pytest, RESEARCH_NOTES 2.2); PR-title/commit check against Conventional Commits; RELEASING.md describes how a release is cut (used by PRD-13).
- Acceptance: PR with non-conforming title fails; fragment required or `no-changelog` label.
- Tests/verification: two test PRs in a fork (one failing, one passing).

### PRD-07 Supply-chain CI: CodeQL, Scorecard, dependency review   [x] (dca26e2)   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `chore/supply-chain-ci`
- Size: M
- Files owned: `.github/workflows/codeql.yml`, `.github/workflows/scorecard.yml`, `.github/workflows/dependency-review.yml`, `.github/dependabot.yml`
- Goal: add the three workflows (per-job permissions, SHA-pinned actions, top-level `contents: read`); add Dependabot docker + grouped updates; upload Scorecard SARIF; record the first Scorecard result in `docs/production-readiness/SCORECARD_BASELINE.md` (owned here).
- Acceptance: workflows green on develop; baseline score recorded with date; any Critical/High Scorecard finding has a linked task.
- Tests/verification: run the workflows; compare with AUDIT section 2.3.

### PRD-08 Container hardening and image scan   [x] (a86c346, 3e89565)   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `chore/container-hardening`
- Size: M
- Files owned: `apps/api/Dockerfile`, `apps/worker/Dockerfile`, `apps/dashboard/Dockerfile`, `.dockerignore`, `.github/workflows/container-scan.yml`
- Goal: non-root `USER`, `HEALTHCHECK`, base images pinned by digest (Dependabot docker keeps them fresh), hash-pinned Python install from `uv.lock`, read-only-rootfs compatibility notes, image scan with fail on High/Critical **[scanner choice open: evaluate Trivy/Grype after reading their docs]**. Does not touch `docker-compose.yml` (PRD-17 owns it).
- Acceptance: `docker run --rm <img> id` is not root; images build reproducibly with the same digest-pinned base; scan job green with documented ignores.
- Tests/verification: CI build + scan; `docker compose up` still healthy (smoke).

### PRD-09 Repo hygiene: binaries and one-off scripts   [ ]   NEW
> Owner decision pending (2026-11-02): the capstone `.docx` and `generate_capstone_diary.py` are intentionally still in the tree. Do not delete them in a docs or hygiene pass.
- Owner type: human-required (decision on capstone diary), agent executes
- Depends on: none
- Branch: `chore/repo-hygiene`
- Size: S
- Files owned: `Radius_Capstone_Project_Diary_FALL_2026.docx`, `generate_capstone_diary.py`, `docs/capstone/*`, `.gitignore`, `.gitattributes`
- Goal: remove binary documents and the generator from the root (move to a release asset or a private location); keep `docs/capstone` only if the owner agrees it should be public. Note: history still holds the file; decide whether that matters.
- Acceptance: no executables or office binaries at root; Scorecard Binary-Artifacts passes.
- Tests/verification: `git ls-files` listing; Scorecard.

### PRD-11 HTTP hardening: headers, CORS, rate limits, body limits   [x] (1e8a4ea)   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/http-hardening`
- Size: M
- Files owned: `apps/api/src/radius_api/main.py`, `apps/api/src/radius_api/middleware/*` (new), `apps/dashboard/next.config.mjs`, `apps/dashboard/middleware.ts`, `apps/api/tests/test_http_hardening.py`
- Goal: CSP (nonce or hashes), HSTS (when behind TLS), `X-Content-Type-Options`, `frame-ancestors`, Referrer-Policy; API CORS allow-list with explicit headers; per-API-key and per-IP rate limits (429 + `Retry-After`); max request body size; webhook route excluded from user limits but size-limited.
- Acceptance: tests assert each header; limit tests prove 429; OWASP API4 row in PRD-27 checklist links to these tests.
- Tests/verification: pytest + a header scan test against the running dashboard in CI.

## 5. Wave 2: release engineering and docs

### PRD-10 Licence headers, REUSE and third-party notices   [ ]   NEW
- Owner type: agent-ok
- Depends on: PRD-01
- Branch: `chore/spdx-reuse`
- Size: M
- Files owned: `LICENSES/`, `REUSE.toml` (or `.reuse/dep5`), `scripts/ci/generate_notices.py`, `.github/workflows/reuse.yml`, source-file headers under `apps/`, `packages/`
- Goal: SPDX identifier in each source file (Best Practices gold), REUSE compliance check **[REUSE spec not fetched; read before implementing]**, generated `THIRD_PARTY_NOTICES` from the existing SBOM job.
- Acceptance: reuse lint passes; notices file generated in release.
- Tests/verification: CI. Header-only bulk change: schedule when no large PRs are open.

### PRD-12 API key lifecycle   [x]   EXT of IT-09
- Owner type: pair
- Depends on: IT-09 design
- Branch: `feature/api-key-lifecycle`
- Size: L
- Files owned: `apps/api/src/radius_api/auth.py`, `infra/database/migrations/versions/*_api_keys.py`, `apps/api/tests/test_auth_keys.py`
- Goal: keys stored hashed, prefix-identifiable, scoped (read/ingest/admin), expirable, revocable, with last-used time; legacy env keys deprecated with warning.
- Acceptance: scope tests (OWASP API5), revoked key rejected, no plaintext key in DB or logs.
- Tests/verification: unit + migration test + log grep test.

### PRD-13 Release pipeline: tags, GHCR, signing, provenance, SBOM   [ ]   NEW
- Owner type: pair (human configures environments/tokens)
- Depends on: PRD-01, PRD-06, PRD-08
- Branch: `feature/release-pipeline`
- Size: L
- Files owned: `.github/workflows/release.yml`, `docs/RELEASING.md` (after PRD-06), `scripts/ci/release_*.py`
- Goal: on a `vX.Y.Z` tag: build linux/amd64+arm64 images for api, worker, dashboard; push to GHCR; cosign keyless sign (OIDC); SLSA provenance via a hosted reusable builder **[choose after reading slsa-framework docs; target L3]**; CycloneDX SBOM per image and per source attached to the GitHub Release; release notes from changelog; `id-token: write` only in the release job.
- Acceptance: `cosign verify` and provenance verification commands documented and run in CI on the published image; Release page contains images list, SBOMs, provenance, notes; Scorecard Signed-Releases 10 on the first release **[Scorecard credits `*.intoto.jsonl` assets on release]**.
- Tests/verification: dry run on a `v0.1.0-rc.N` tag in a fork; verify commands in a separate job.

### PRD-14 Python and npm packaging metadata   [ ]   EXT of IT-02
- Owner type: agent-ok
- Depends on: PRD-01, IT-02
- Branch: `chore/packaging`
- Size: M
- Files owned: `pyproject.toml` (metadata tables only), `package.json` (root metadata), CLI package files
- Goal: licence, authors, URLs, classifiers, README; publish the `radius` CLI via PyPI trusted publishing with attestations (pytest does this, RESEARCH_NOTES 2.2).
- Acceptance: `pip install radius-cli` in a clean venv runs `radius --version`; PyPI shows attestations.
- Tests/verification: TestPyPI dry run.

### PRD-15 OpenAPI contract, stability policy, client SDK   [ ]   EXT of IT-09
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/openapi-contract`
- Size: M
- Files owned: `docs/api/openapi.json` (generated), `scripts/ci/export_openapi.py`, `docs/API_STABILITY.md`, `packages/sdk-*`
- Goal: committed OpenAPI export checked in CI for drift; breaking-change detection against the last release **[tool open: evaluate oasdiff or similar]**; stability policy (declared public surface per SemVer: HTTP API `/v1`, CLI flags, Action inputs, config keys; deprecation = one minor release minimum); generated TypeScript and Python clients.
- Acceptance: CI fails on undeclared breaking change; SDKs build and call the API in an integration test.
- Tests/verification: contract test in CI.

### PRD-16 Helm chart   [ ]   NEW
- Owner type: pair
- Depends on: PRD-08, PRD-13 (images)
- Branch: `feature/helm-chart`
- Size: L
- Files owned: `infra/helm/radius/**`, `.github/workflows/helm.yml`
- Goal: chart following Helm best practices (values, labels, RBAC minimal, probes from `/health` `/ready`, securityContext non-root, PodDisruptionBudget, optional external Postgres, migrations as a Job/hook, secrets by reference); published as OCI to GHCR and signed.
- Acceptance: `helm lint` and `helm template` pass; install on `kind` in CI reaches a verdict on a seeded PR.
- Tests/verification: kind e2e workflow.

### PRD-17 Operator documentation set   [~] (docs/operations set and generated config reference done on `docs/truth-and-operator-docs`; the generator lives at `scripts/gen_config_reference.py` with a unit test, not `scripts/ci/`. Not done: `docker-compose.prod.yml` with published images (no images exist, PRD-13), Terraform example, CI upgrade test, a reviewer-run upgrade drill)   NEW
- Owner type: agent-ok
- Depends on: PRD-13 (for image names), PRD-16 optional
- Branch: `docs/operations`
- Size: L
- Files owned: `docs/DEPLOYMENT.md`, `docker-compose.yml`, `docker-compose.prod.yml`, `docs/operations/*`, `infra/terraform/**` (example), `scripts/ci/gen_config_reference.py`
- Goal: production compose using published images; generated config/env reference from settings classes; upgrade and rollback guide (including migration order); hardening guide; backup/restore cross-linked to QS-11; runbooks (queue backlog, stuck jobs, GitHub rate limits, DB failover); secrets guidance; Terraform example.
- Acceptance: a reviewer who did not write it upgrades 0.1.x to 0.2.x following only the guide; config reference regenerates without diff in CI.
- Tests/verification: upgrade test script in CI (previous image + new image + migrations).

### PRD-18 Docs site in Diataxis shape   [ ]   EXT of PL-05
- Owner type: agent-ok
- Depends on: PL-05 scope, IT-09 for reference
- Branch: `docs/site`
- Size: L
- Files owned: `docs-site/**`, `.github/workflows/docs.yml`, `docs/README.md` (index)
- Goal: static docs site (generator choice open) with the four forms: tutorials (first verdict), how-to guides (CI integration, policies, deployment), reference (API, config, CLI, Action), explanation (concepts: evidence, uncalibrated score, sandbox model, limits). Move or link the phase-era files in `docs/` into an archive section rather than deleting.
- Acceptance: build and link check in CI; every public feature has a reference entry (checklist in the PR); quickstart tested by someone new (PL-05).
- Tests/verification: link checker; docs-coverage script (see DoD).

### PRD-19 ADRs, public roadmap, maintainers growth   [ ]   NEW
- Owner type: pair
- Depends on: PRD-03
- Branch: `docs/adr-roadmap`
- Size: S
- Files owned: `docs/adr/*`, `docs/roadmap.md`, `.github/CODEOWNERS`
- Goal: ADR template and numbered ADRs for the main decisions already in `docs/decisions.md`; outcome-level public roadmap; CODEOWNERS split by area once a second maintainer exists.
- Acceptance: ADR index; roadmap has "now/next/later" with evidence links.
- Tests/verification: link check.

## 6. Wave 3: quality

### PRD-20 Dogfood mutation testing   [ ]   NEW
- Owner type: agent-ok
- Depends on: none (uses nightly workflow)
- Branch: `feature/dogfood-mutation`
- Size: M
- Files owned: `.github/workflows/mutation.yml`, `scripts/ci/mutation_*.py`, `docs/quality/MUTATION.md`
- Goal: nightly mutation run on the confidence and diff-parsing packages with a stored score and a ratchet; Radius reports its own score on its own PRs (eat your own dogfood). Tool choice open (mutmut and Stryker exist as peers, RESEARCH_NOTES 2.1).
- Acceptance: mutation score published per package; surviving mutants triaged into issues; no flake in CI (nightly only).
- Tests/verification: workflow run artifact.

### PRD-21 Property and fuzz tests   [ ]   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `test/property-fuzz`
- Size: M
- Files owned: `tests/property/**`, `pyproject.toml` (dev dependency group only; coordinate with PRD-14 via separate sections)
- Goal: property tests for diff-hunk parser, module resolver, JUnit parser, webhook payload parsing; seeds checked in; Scorecard Fuzzing recognises language-native fuzzing **[detection rules unverified; confirm with a scorecard run]**.
- Acceptance: >= 1 property per parser input boundary; failures minimised and added as regression cases.
- Tests/verification: CI run with fixed seed + nightly random.

### PRD-22 Browser e2e and accessibility CI   [ ]   EXT of QS-12
- Owner type: agent-ok
- Depends on: none
- Branch: `test/dashboard-e2e-a11y`
- Size: L
- Files owned: `apps/dashboard/e2e/**`, `apps/dashboard/package.json` (dev deps), `.github/workflows/e2e.yml`
- Goal: Playwright against the compose stack: sign-in, analysis list, graph, ingestion modal; axe checks per page; keyboard path for the graph (WCAG 2.2: 2.5.7 alternative to dragging, 2.4.11 focus not obscured, 2.5.8 target size, 3.3.8 accessible authentication).
- Acceptance: zero serious/critical axe violations on listed pages; manual screen-reader pass recorded for 3 flows (human).
- Tests/verification: CI job with HTML report artifact.

### PRD-23 Published performance results   [ ]   EXT of QS-07
- Owner type: agent-ok
- Depends on: QS-07
- Branch: `docs/perf-results`
- Size: M
- Files owned: `docs/benchmarks/PERFORMANCE.md`, `benchmarks/load/**`
- Goal: after QS-07 yields a harness, publish p50/p95/p99 for webhook-to-verdict and API reads on a stated machine, with variance, nightly trend artifact.
- Acceptance: numbers in the doc are produced by a script in the repo.
- Tests/verification: rerun reproduces within stated tolerance.

### PRD-24 Coverage ratchet and flaky-test enforcement   [ ]   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `chore/coverage-ratchet`
- Size: S
- Files owned: `.github/workflows/coverage.yml`, `pyproject.toml` ([tool.coverage] section only), `docs/FLAKY_TESTS.md`, `.test_quarantine.json`
- Goal: branch coverage on; gate never decreases (store baseline); quarantine file with expiry dates (posthog pattern, RESEARCH_NOTES 2.1); JS coverage reported.
- Acceptance: PR lowering coverage fails; quarantined tests expire into failures.
- Tests/verification: test PRs.

### PRD-25 Install-to-first-verdict timing harness   [ ]   EXT of PL-03
- Owner type: agent-ok
- Depends on: PRD-13 (published images), PRD-05
- Branch: `test/time-to-first-verdict`
- Size: M
- Files owned: `scripts/ci/ttfv.py`, `.github/workflows/ttfv.yml`, `docs/quality/TTFV.md`
- Goal: script that starts from a clean VM/container with only Docker, follows README quickstart, seeds the demo repo, and records elapsed time to first verdict; run weekly on a clean runner and manually on a laptop.
- Acceptance: median < 10 minutes over 5 runs recorded.
- Tests/verification: artifact with timestamps.

## 7. Wave 4: security and operations

### PRD-26 SSO/OIDC and session security   [ ]   NEW
- Owner type: pair
- Depends on: MG-06 design
- Branch: `feature/oidc-sso`
- Size: L
- Files owned: `apps/api/src/app/routes_auth.py`, `apps/dashboard/app/**/sign-in`, `apps/dashboard/middleware.ts` (coordinate with PRD-11 via sequencing)
- Goal: OIDC login (GitHub plus generic OIDC), secure cookies, CSRF protection for state-changing dashboard calls, session expiry/rotation, logout everywhere.
- Acceptance: test IdP in CI; CSRF test; no tokens in localStorage.
- Tests/verification: e2e from PRD-22.

### PRD-27 ASVS and API Top 10 mapping with tests   [ ]   NEW
- Owner type: pair
- Depends on: QS-01
- Branch: `docs/asvs-mapping`
- Size: M
- Files owned: `docs/security/ASVS_MAPPING.md`, `docs/security/API_TOP10.md`, `tests/security/test_asvs_*.py`
- Goal: first read ASVS 5.0 primary text (level and chapter definitions were not verified in this audit); map Level 1 requirements and relevant Level 2 chapters (authentication, session, access control, validation, API, logging, configuration) to a repo test or documented gap; same for API Top 10 2023 items API1-API10 (names in RESEARCH_NOTES 1.9). Include webhook signature and replay tests.
- Acceptance: every row has status met/partial/gap with a link; gaps become issues; no "met" without a test or code reference.
- Tests/verification: reviewer spot-checks 10 random rows.

### PRD-28 Operational policies: migrations, shutdown, health   [ ]   NEW
- Owner type: agent-ok
- Depends on: none
- Branch: `feature/ops-policies`
- Size: M
- Files owned: `docs/operations/MIGRATIONS.md`, `scripts/ci/check_migration_compat.py`, `apps/worker/src/**` (shutdown handling only), `apps/api/src/radius_api/routes/health.py`
- Goal: expand/contract migration rule with a CI check that old app version runs against new schema; SIGTERM drains in-flight jobs in worker and API (12-factor Disposability); worker health endpoint; job lease recovery test.
- Acceptance: kill-during-job test shows the job is retried exactly once without duplicate publish.
- Tests/verification: integration test with real Postgres.

### PRD-29 Privacy, telemetry and legal templates   [ ]   EXT of QS-06
- Owner type: human-required (legal review) with agent drafts
- Depends on: QS-06
- Branch: `docs/privacy-pack`
- Size: M
- Files owned: `docs/legal/*`, `docs/TELEMETRY.md`
- Goal: privacy notice template, DPA/subprocessor notes (LLM providers, GitHub), data-flow diagram, retention table, telemetry policy (off by default, documented fields, how to verify); mirrors semgrep `metrics.md` practice.
- Acceptance: lawyer or qualified reviewer sign-off recorded; telemetry code (if any) matches the doc, tested.
- Tests/verification: test asserts no network call when telemetry disabled.

### PRD-30 External security review   [ ]   EXT of QS-03
- Owner type: human-required
- Depends on: PRD-27, QS-01, QS-03, PRD-11, PRD-12
- Branch: n/a
- Size: L
- Files owned: `docs/security/REVIEW_<date>.md` (summary only)
- Goal: independent pen test or review of API, dashboard, sandbox and GitHub App flows; Best Practices gold requires a security review within 5 years.
- Acceptance: no open High/Critical findings at v1.0; summary published.
- Tests/verification: report plus retest.

## 8. Wave 5: ecosystem and gate

### PRD-31 Research artifact packaging   [ ]   NEW
- Owner type: pair
- Depends on: EP-xx results
- Branch: `docs/research-artifacts`
- Size: L
- Files owned: `CITATION.cff`, `docs/research/REPRODUCE.md`, `.zenodo.json`, `scripts/repro/**`
- Goal: single-command reproduction of reported tables from pinned data and container; dataset licences recorded per `docs/research/datasets/INVENTORY.md`; Zenodo DOI minted on release; paper build in CI.
- Acceptance: independent machine reproduces tables within stated tolerance.
- Tests/verification: CI reproduction job on a small slice, full run manual.

### PRD-32 Distribution: Action, MCP, registries   [ ]   EXT of IT-03/IT-04
- Owner type: pair
- Depends on: IT-03, IT-04, PRD-13
- Branch: `chore/distribution`
- Size: M
- Files owned: `radius-action` repo or `action.yml` at root (decision), `docs/distribution.md`
- Goal: Action in its own tagged repo (`v1` moving tag) listed on Marketplace; MCP server published to its package registry and a directory.
- Acceptance: workflow in `docs/examples/radius-ci-workflow.yml` uses the published Action by tag.
- Tests/verification: example repo CI.

### PRD-33 Status and support process   [ ]   NEW
- Owner type: human-required
- Depends on: hosted offering decision
- Branch: n/a
- Size: S
- Files owned: `SUPPORT.md` (after PRD-03), `docs/operations/INCIDENTS.md`
- Goal: status page (hosted only), incident template, triage SLAs for issues and security reports.
- Acceptance: first-response target published; measured over 30 days.
- Tests/verification: issue timestamps.

### PRD-34 Best Practices badge and Scorecard ratchet   [ ]   NEW
- Owner type: human-required (registration), agent fills answers
- Depends on: PRD-03, PRD-07, PRD-13
- Branch: `docs/best-practices-badge`
- Size: M
- Files owned: `docs/production-readiness/BADGE_ANSWERS.md`, README badge lines
- Goal: register on bestpractices.dev, answer each passing criterion with a repo link, then silver/gold gap list; CI job fails if Scorecard drops below the recorded floor.
- Acceptance: passing badge earned; floor file committed.
- Tests/verification: badge page.

### PRD-35 v1.0 gate review   [ ]   NEW
- Owner type: human-required
- Depends on: all above that the checklist in section 9 names
- Branch: `docs/v1-gate`
- Size: S
- Files owned: `docs/production-readiness/V1_GATE.md`
- Goal: run section 9 checklist, record evidence links and date; go/no-go.
- Acceptance: every box checked with evidence, or an explicit waiver with owner and date.
- Tests/verification: second reviewer.

### PRD-36 i18n readiness (post-1.0)   [ ]   NEW
- Owner type: agent-ok
- Depends on: PRD-22
- Branch: `feature/dashboard-i18n`
- Size: M
- Files owned: `apps/dashboard/lib/i18n/**`
- Goal: externalise dashboard strings; no locale shipped beyond English until demanded.
- Acceptance: lint rule forbids new hard-coded user-facing strings.
- Tests/verification: lint.

## 9. Definition of done for v1.0 (checkable)

Every line needs an evidence link in `V1_GATE.md`. Numeric thresholds are proposals chosen by the audit author; the owner may change them with a recorded decision. Thresholds not derived from a fetched source are marked (proposal).

**Community and legal**
- [ ] LICENSE and NOTICE present; Scorecard License = 10 (source: Scorecard scoring table, RESEARCH_NOTES 1.1).
- [ ] GitHub community profile: README, CoC, CONTRIBUTING, LICENSE, issue templates all green.
- [ ] SECURITY.md with contact and disclosure process; first-response target <= 14 days (Best Practices passing criterion); Scorecard Security-Policy >= 9.
- [ ] REUSE/SPDX check passes (PRD-10); third-party notices generated for the release.
- [ ] Privacy notice, telemetry policy and DPA notes reviewed (PRD-29).

**Supply chain**
- [ ] OpenSSF Scorecard overall >= 7.5 (proposal) with: Binary-Artifacts 10, Dangerous-Workflow 10, Token-Permissions 10, Pinned-Dependencies >= 8, Dependency-Update-Tool 10, SAST >= 8, Security-Policy >= 9, License 10, Vulnerabilities 10, Signed-Releases 10, SBOM 10, Branch-Protection >= 6 (single-maintainer limits tiers 4-5, per tier table).
- [ ] Release artifacts (images, CLI) signed with cosign keyless and carry SLSA build provenance at L3 using a hosted isolated builder; verification commands in docs and run in CI.
- [ ] SBOM (CycloneDX) attached to every release and image.
- [ ] 0 open High/Critical findings from pip-audit, pnpm audit (no baseline entries) and image scan at release time.
- [ ] Best Practices badge: passing earned; silver gap list published.

**Quality**
- [ ] Python statement coverage >= 85% (proposal; currently gated at 83%) and branch coverage measured and ratcheted; silver target 80% statement is already met by that gate if the gate is accurate.
- [ ] Mutation score reported nightly for core packages with a recorded floor (PRD-20).
- [ ] Property/fuzz tests on all parser entry points (PRD-21).
- [ ] Browser e2e on the 4 main flows green; no quarantined test older than its expiry.
- [ ] Performance: p95 webhook-to-published-verdict and p95 API read latency measured by repo scripts on a documented machine, targets set by the owner before the run (proposal: API read p95 < 300 ms; verdict for a median PR < 5 min), results in `docs/benchmarks/PERFORMANCE.md`.

**Security**
- [ ] Threat model (QS-01) reviewed by a second person; every High risk has a mitigation task closed.
- [ ] ASVS 5.0 Level 1 mapping complete with no unexplained "gap"; Level 2 chapters for authentication, session, access control, API exist with test links (PRD-27).
- [ ] OWASP API Top 10 2023: all ten rows have a status and test or accepted risk.
- [ ] Tenant isolation suite (QS-04) green; scoped, hashed, revocable API keys (PRD-12); rate limits and security headers tested (PRD-11).
- [ ] External review done with no open High/Critical (PRD-30).

**Accessibility**
- [ ] axe CI reports 0 serious/critical violations on all dashboard routes; manual keyboard + screen-reader audit recorded against WCAG 2.2 AA, including 2.4.11, 2.5.7, 2.5.8, 3.3.8.

**Release and operations**
- [ ] Tagged SemVer release; CHANGELOG follows Keep a Changelog; images on GHCR for amd64 and arm64.
- [ ] Helm chart installs on kind in CI and upgrade test from previous release passes (PRD-16, PRD-17).
- [ ] SLOs defined with alert rules (QS-08); backup restore drill done with recorded RTO/RPO (QS-11).
- [ ] Graceful shutdown and migration-compat checks in CI (PRD-28).

**Product and docs**
- [ ] Install-to-first-verdict median < 10 minutes over 5 clean-machine runs (PRD-25).
- [ ] Docs site live with all four Diataxis forms; link check green; every CLI command, Action input, API endpoint and config key has a reference entry (script-checked, proposal 100%).
- [ ] API stability policy published; OpenAPI export in CI; no breaking change without major bump (PRD-15).
- [ ] Demo repo with 4 scripted PRs (PL-04); GitHub Action and CLI published (PRD-14, PRD-32).

**Research**
- [ ] CITATION.cff and DOI; reproduction script regenerates reported tables (PRD-31).

## 10. Dependency and ownership notes for parallel agents

- Wave 1 tasks may all start at once; paths do not overlap. Shared file `pyproject.toml` is touched by PRD-14, PRD-21, PRD-24: each edits a different table; rebase on develop and keep edits table-scoped. `docker-compose.yml` is owned by PRD-17 only; PRD-08 must not edit it.
- `.github/workflows/*`: each task owns its own new file; only PRD-24 edits `coverage.yml`; nobody else edits `ci.yml`/`security.yml` without a separate "CI plumbing" PR.
- `.github/dependabot.yml` is PRD-07 only. `.github/CODEOWNERS` is PRD-19 only.
- Human-required first steps: PRD-01 (licence), PRD-02 (mailbox, settings), PRD-09 (capstone files decision), PRD-29 and PRD-30 (legal/pen test), PRD-33, PRD-34 registration, PRD-35 gate.
