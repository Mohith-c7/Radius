# Production-readiness audit

Baseline: `origin/develop` at fc27598 (2026-11-02). Method: read the repo files named below; compare to the standards and exemplar repos in [RESEARCH_NOTES.md](RESEARCH_NOTES.md). Radius is at version 0.1.0 (`pyproject.toml`, `package.json`).

**What this is not.** No Scorecard run, no badge application, no pen test and no WCAG audit has been done. "Missing" means "not found in the tree at the checked path". Several settings live in GitHub, not in git (branch protection, secret scanning, 2FA, repo visibility); those are marked **[needs human check]**. Nothing here claims Radius meets a standard.

Legend. Severity: **blocker** = cannot publish as a credible OSS project / cannot be run safely by a third party; **high**; **medium**; **low**. Effort: S < 1 day, M 1-3 days, L 3-5 days. Task ids: `PRD-nn` are new tasks in [BACKLOG.md](BACKLOG.md); existing research-plan ids (`QS-`, `IT-`, `PL-`, `MG-`, `F-`, `EP-`) are cross-referenced, not duplicated.

## 1. Existing strengths (evidence in repo)

| Area | Evidence |
|---|---|
| CI with least-privilege token | `.github/workflows/*.yml` top-level `permissions: contents: read` (security.yml line 14; ci.yml line 13) |
| Actions pinned to commit SHAs | `uses: actions/checkout@11d5960a... # v4.4.0` in ci.yml, security.yml |
| Secret scan on full history | `security.yml` gitleaks, image pinned by digest; `.gitleaks.toml` |
| Dependency audits and licence gate | `security.yml`: pip-audit (blocking), pnpm audit with expiring baseline `.github/security/audit-baseline.json`, CycloneDX SBOM + licence policy (blocks AGPL/SSPL/GPL) uploaded as artifact |
| Coverage gate | `coverage.yml`, `COVERAGE_MIN: "83"` |
| Nightly benchmarks | `nightly.yml` |
| Dependabot | `.github/dependabot.yml` (actions, pip, npm, weekly) |
| CODEOWNERS and PR template | `.github/CODEOWNERS` (`* @Mohith-c7`), `.github/pull_request_template.md` |
| Health and readiness endpoints | `apps/api/src/radius_api/routes/health.py` (`/health`, `/ready`) |
| Compose healthchecks | `docker-compose.yml` lines 18, 65 |
| Versioned DB migrations | `infra/database/migrations/versions/` (5 Alembic revisions) |
| Flaky-test, CI and security docs | `docs/FLAKY_TESTS.md`, `docs/security/CI_CHECKS.md`, `EXECUTION_ISOLATION.md`, `PROMPT_INJECTION.md` |
| Honest claims policy | README states the score is an uncalibrated heuristic; experimental parsers labelled |
| Reusable GitHub Action | `.github/actions/radius-verify/action.yml` |
| Observability baseline | `docs/OBSERVABILITY.md`, `infra/observability/prometheus.yml` |
| Test and benchmark corpora | `tests/`, `benchmarks/`, `docs/benchmarks/REAL_REPO_BENCHMARK.md` |

## 2. Scorecard

### 2.1 Repository community files

| Area | Standard / source | Current evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| LICENSE | GitHub profile; Scorecard License; Best Practices Basics | No `LICENSE` at root of develop; `pyproject.toml` has no licence field. NOTICE/LICENSE may arrive from `docs/finalize-decisions`, whose tree (checked locally at fc27598) does not contain them either | Licence undecided | blocker | S (human decision) | PRD-01 (QS-13) |
| README | GitHub profile; peers (2.1 of notes) | `README.md` has capabilities and architecture; honest caveats | No badges, screenshot/GIF, 10-minute quickstart at top, install paths, comparison, links to docs site | high | S | PRD-05 |
| CONTRIBUTING | GitHub profile; Best Practices | Missing (dev flow only in `docs/DEVELOPMENT_GUIDE.md`) | Missing at root/`.github` | blocker | S | PRD-03 |
| CODE_OF_CONDUCT | GitHub profile | Missing | Missing | high | S | PRD-03 |
| SECURITY.md + disclosure | Scorecard Security-Policy; Best Practices Reporting (14-day response) | Missing (no SECURITY.md in tree) | No contact, no process, no supported-versions table | blocker | S (+ human mailbox) | PRD-03, PRD-02 |
| SUPPORT | peers | Missing | Missing | medium | S | PRD-03 |
| GOVERNANCE / MAINTAINERS | Best Practices silver | Missing; CODEOWNERS has one owner | Roles, decision process, bus-factor plan | medium | S | PRD-03 |
| Issue forms / Discussion templates | GitHub profile | `.github/` has only a PR template | No `ISSUE_TEMPLATE`, no discussion categories | high | S | PRD-04, PRD-02 |
| CHANGELOG | Keep a Changelog; peers | Missing at root (only `docs/research/preregistration/CHANGELOG.md`) | No user-facing changelog or fragment mechanism | high | S | PRD-06 |
| Roadmap | peers | `docs/roadmap.md`, `docs/milestones.md` exist (internal/phase style) | No public, outcome-level roadmap | low | S | PRD-19 |
| ADRs | peers | `docs/decisions.md` (single running file) | No numbered ADR directory with status | low | S | PRD-19 |
| Agent policy file | semgrep/renovate/posthog (AGENTS.md, AI_POLICY.md) | `docs/AI_CONTEXT.md` exists, not at root | Root AGENTS.md and contribution policy for AI-authored PRs | medium | S | PRD-03 |
| CITATION.cff | pytest has CITATION; research track | Missing | Needed for the paper and DOI | medium | S | PRD-31 |
| Commit convention enforcement | Conventional Commits; renovate `check-commit-messages.yml` | Convention stated in task docs, not enforced in CI | No commit/PR-title lint | medium | S | PRD-06 |
| Repo hygiene | Scorecard Binary-Artifacts | `Radius_Capstone_Project_Diary_FALL_2026.docx` at root and in `docs/capstone/`; `generate_capstone_diary.py` at root | Binaries and a one-off script in root of a public repo | medium | S (human OK to move) | PRD-09 |

### 2.2 Licensing and compliance

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Third-party notices | Licence terms of deps; Sentry licence gate | SBOM + licence report artifact in `security.yml`; no committed notice file | `THIRD_PARTY_NOTICES` generated at release | medium | S | PRD-10 |
| SPDX / REUSE headers | Best Practices gold; REUSE **[spec not fetched]** | No SPDX headers checked (not exhaustively verified) | Header policy and CI check | low | M | PRD-10 |
| DCO or CLA | Best Practices silver | Missing | Decision + bot/check | medium | S | PRD-01, PRD-03 |
| Borrowed-code review | QS-13 | Open in plan | Needs sign-off before open-sourcing | high | S | QS-13 |

### 2.3 Supply chain

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Pinned actions | Scorecard Pinned-Dependencies | SHA pins present | none found in workflows read | - | - | - |
| Pinned base images | Scorecard Pinned-Dependencies | `FROM python:3.12-slim`, `FROM node:22-slim` (tags, no digest) in `apps/*/Dockerfile`; compose line 136 | Pin by digest, update via Dependabot docker ecosystem | medium | S | PRD-08 |
| Dependency update tool | Scorecard | Dependabot for actions/pip/npm | No docker ecosystem, no grouping, no `uv` lock policy | low | S | PRD-07 |
| Python lock | Scorecard Pinned | `uv.lock` present; `pyproject.toml` uses `>=` ranges; `apps/api/requirements.txt` exists | Document which is source of truth; hash-pinned install in images | medium | M | PRD-08 |
| Signed releases | Scorecard Signed-Releases (8 / 10 with SLSA provenance); SLSA L2/L3 | No release workflow, no tags policy, no signing | Entire pipeline missing | blocker | L | PRD-13 |
| SLSA provenance | SLSA v1.0 L3 | none | needs hosted isolated builder + provenance | high | M | PRD-13 |
| SBOM with release | Scorecard SBOM (+5 for release artifact) | SBOM generated in CI as an artifact only | Attach to release; add image SBOM | medium | S | PRD-13 |
| Container image scanning | OSV/Trivy-class scanners **[tool not fetched]** | None | Scan images in CI | high | S | PRD-08 |
| Static analysis | Scorecard SAST; Best Practices passing | ruff/lint/typecheck in `ci.yml`; no CodeQL/Semgrep | Add CodeQL | high | S | PRD-07 |
| Dependency review on PRs | renovate `dependency-review.yml` | None | Add | medium | S | PRD-07 |
| Scorecard in CI | renovate `scorecard.yml` | None | Add + publish results | medium | S | PRD-07 |
| Dangerous workflows | Scorecard (Critical) | Workflows use `pull_request`; `pull_request_target` not checked exhaustively | Run scorecard to confirm | medium | S | PRD-07 |
| Branch protection | Scorecard tiers | `docs/github-branch-protection.md`, `scripts/apply-github-branch-protection.ps1`; only `Validate` required (`docs/security/CI_CHECKS.md`); actual state **[needs human check]** | Add new checks as required; 2 reviewers is impractical with 1 maintainer, so aim tier 3 | high | S | PRD-02 |
| CODEOWNERS | Scorecard T4 | Single owner for `*` | Per-area owners when team grows | low | S | PRD-19 |
| Secret scanning | Best Practices | gitleaks in CI; GitHub push protection **[needs human check]** | Enable push protection | medium | S | PRD-02 |
| Dockerfile non-root | CIS-style practice **[source not fetched]** | No `USER` instruction in any of the 3 Dockerfiles; no `HEALTHCHECK` | Run as non-root, add HEALTHCHECK | high | S | PRD-08 |

### 2.4 Release engineering

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Versioning policy | SemVer | `0.1.0` in both manifests; branch flow in DEVELOPMENT_GUIDE ("main is release branch") | No declared public API (HTTP API, CLI, Action inputs), no tag convention | high | S | PRD-13, PRD-15 |
| Release notes automation | Conventional Commits + peers | none | Generate from fragments/commits | medium | M | PRD-06, PRD-13 |
| Container images on GHCR, multi-arch | Plausible `build-public-images-ghcr.yml` | none published | Build/push linux/amd64+arm64 | blocker | M | PRD-13 |
| PyPI/npm packages | Scorecard Packaging; pytest trusted publishing | none; CLI is IT-02 | Publish CLI via trusted publishing after IT-02 | medium | M | PRD-14 (IT-02) |
| Helm chart | Helm best practices | none (`infra/` has database, observability only) | Chart + kind install test | high | L | PRD-16 |
| Terraform example | Plausible `terraform-e2e.yml` | none | Reference module | low | M | PRD-17 |
| GitHub Action published | Marketplace | `.github/actions/radius-verify` is a local composite action | Own repo/tags `v1`, Marketplace listing (IT-03) | high | M | PRD-32 (IT-03) |
| Docs site | Diataxis; Plausible `publish-docs.yml` | 30+ markdown files in `docs/`, many phase-era; no site, no nav | Restructure into 4 forms, build + link check in CI | high | L | PRD-18 (PL-05) |
| Upgrade guide / config reference | 12-factor Config; Sentry self-hosted | `docs/DEPLOYMENT.md` (compose, env section), `.env.example` | No upgrade/rollback guide, no full env reference | high | M | PRD-17 |

### 2.5 Quality

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Unit/integration tests | Best Practices | pytest across packages, `apps/*/tests`, `tests/`; Node tests for dashboard | none for existence | - | - | - |
| Coverage level and trend | Best Practices silver 80% / gold 90% stmt, 80% branch | gate 83% (`coverage.yml`), statement only, no trend | Branch coverage, ratchet, publish trend | medium | S | PRD-24 |
| Browser e2e | peers (plausible `e2e/`) | `tests/test_e2e_webhook_to_comment.py` (API level); dashboard tests are `node --test` `.mjs` | No browser tests | high | M | PRD-22 |
| Mutation testing of Radius | Dogfooding; mutmut/Stryker are peers | none (grep for mutmut/stryker in manifests found none) | Run mutation on core packages nightly | medium | M | PRD-20 |
| Property/fuzz tests | Scorecard Fuzzing | no `hypothesis` in `pyproject.toml` or tests (grep) | Parser/diff/webhook property tests | medium | M | PRD-21 |
| Performance/load | QS-07; semgrep `perf/` | `benchmarks/` is accuracy/selection oriented | No load/latency targets | high | M | QS-07, PRD-23 |
| Flaky policy | posthog quarantine file | `docs/FLAKY_TESTS.md` | Enforcement automation unverified | low | S | PRD-24 |
| Install-to-first-verdict time | PL-03 | not measured | Harness on clean machine | high | M | PRD-25 |

### 2.6 Security

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Threat model | QS-01; Best Practices silver assurance case | Not written; `docs/security/` has execution isolation and prompt injection notes | Write | high | M | QS-01 |
| Sandbox pen test | QS-03 | open | Needed before multi-tenant | high | L | QS-03, PRD-30 |
| AuthN | OWASP API2 | `apps/api/src/radius_api/auth.py`: org id + API key headers, keys from settings string | No scopes (grep for scope found only a docstring), no rotation/hashing/expiry, shared static key | high | M | IT-09, PRD-12 |
| SSO/OIDC for dashboard | ASVS (mapping unverified) | `apps/api/src/app/routes_auth.py`, dashboard sign-in pages exist; SSO not found | SSO/OIDC, session review, CSRF | medium | L | PRD-26 |
| RBAC and audit log | OWASP API5 | planned | not built | high | L | MG-06 |
| Tenant isolation tests | OWASP API1 | `tests/security/` has prompt injection only | Cross-tenant object access tests | high | M | QS-04 |
| Rate limiting / resource limits | OWASP API4 | rate limiting only in the LLM provider code; none found on API routes | Per-key limits, body size limits | high | M | PRD-11 |
| Security headers, CSP | ASVS / Best Practices gold for sites | `next.config.mjs`, `middleware.ts`, `main.py`: no header configuration found (grep) | CSP, HSTS, nosniff, frame-ancestors | high | S | PRD-11 |
| CORS | OWASP API8 | `main.py` lines 109-119: origins from settings, `allow_headers=["*"]` | Tighten, document defaults | medium | S | PRD-11 |
| Webhook auth | Scorecard Webhooks (repo level) | GitHub webhook handler exists (`routes/github_webhooks.py`); signature verification not re-verified in this audit | Confirm signature check + replay protection tests | medium | S | PRD-27 |
| Secrets management | 12-factor Config | `.env.example`, env-driven | Secrets in K8s Secret / external store guidance | medium | S | PRD-17 |
| Data retention / PII | QS-06 | open | Policy + enforcement | high | M | QS-06, PRD-29 |
| Vulnerability disclosure | Best Practices | missing | see 2.1 | blocker | S | PRD-03 |
| ASVS / API Top 10 mapping | OWASP ASVS 5.0, API Top 10 2023 | none | Checklist with test per item | high | M | PRD-27 |

### 2.7 Reliability and operations

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Health/readiness | k8s practice | `/health`, `/ready`; queue depth provider | Worker has no health endpoint (not checked in detail) | low | S | PRD-28 |
| Graceful shutdown | 12-factor Disposability | not verified in `apps/*/src` (grep for SIGTERM/lifespan inconclusive) | Test and document | medium | S | PRD-28 |
| Zero-downtime migrations | expand/contract | Alembic; no policy or CI check for backward-compat | Policy + migration test with previous app version | medium | M | PRD-28 |
| SLOs and alerts | QS-08 | `docs/OBSERVABILITY.md`, `infra/observability/prometheus.yml` | No SLO definitions, alert rules, dashboards | high | M | QS-08 |
| Backups/DR | QS-11 | open | restore drill | high | M | QS-11 |
| Runbooks | peers | `docs/github-app-validation/RUNBOOK.md` only | Operator runbooks | medium | M | PRD-17 |
| Capacity/load | QS-07 | none | see 2.5 | high | M | QS-07 |
| Cost controls | QS-10 | open | LLM spend caps | medium | M | QS-10 |

### 2.8 Deployment

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Docker Compose | Sentry/Plausible | `docker-compose.yml`, `docs/DEPLOYMENT.md` | Production variant uses build contexts, not published images; compose line 136 inline `FROM` | medium | S | PRD-13, PRD-17 |
| Helm/K8s | Helm best practices | none | see 2.4 | high | L | PRD-16 |
| Hardening guide | Best Practices silver "hardening" | `docs/security/EXECUTION_ISOLATION.md` covers sandbox | Operator-facing hardening guide | medium | S | PRD-17 |
| Config reference | 12-factor | `.env.example`; no generated table | Generate from pydantic settings | medium | S | PRD-17 |

### 2.9 Product

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Onboarding under 10 minutes | PL-03 | `dev:stack` script; `scripts/seed_demo.py` | No measured path; no sample PR | high | L | PL-03, PRD-25 |
| Demo repo | PL-04 | none | | medium | M | PL-04 |
| Integrations: Action, CLI, MCP | IT-02..04 | action exists locally; CLI/MCP open | | high | L | IT-02, IT-03, IT-04 |
| Dashboard accessibility | WCAG 2.2 AA | `aria-` appears in only 2 component files (grep count); no automated a11y test | Audit + axe CI; check 2.5.7 drag alternatives on graph, 2.5.8 target size | high | M | QS-12, PRD-22 |
| i18n | optional | none | Post-1.0 | low | M | PRD-36 |
| Public API docs / SDK | OpenAPI 3.x; IT-09 | FastAPI app (OpenAPI served by default; `/docs` config not verified); `docs/API_CONTRACTS.md`, `docs/api.md` | No published spec file, no contract test, no SDK | high | M | IT-09, PRD-15 |
| Status / changelog page | peers | none | | low | S | PRD-33 |

### 2.10 Community and ecosystem

| Area | Standard | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|---|
| Discussions | Best Practices "searchable discussion mechanism" | **[needs human check]** | Enable + categories | medium | S | PRD-02, PRD-04 |
| good-first-issue funnel | Best Practices gold | none | Label scheme + seed issues | medium | S | PRD-04 |
| Rule-pack plugin interface | IT-08 | open | | medium | L | IT-08 |
| Contributor diversity | Scorecard Contributors; Best Practices gold | single owner in CODEOWNERS | Time-bound goal; cannot be solved by docs | low | - | PRD-19 |
| Badge programme | Best Practices | none | Register project, answer criteria | medium | M | PRD-34 |

### 2.11 Research artifacts

| Area | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|
| Reproducibility package | `docs/research/datasets/`, `preregistration/`, `benchmarks/` | single-command repro, pinned environment, data hygiene check | high | L | PRD-31 (EP-xx) |
| Dataset release | `docs/research/datasets/INVENTORY.md`, `DATA_HYGIENE.md` | licence per dataset, hosting, DOI | medium | M | PRD-31 |
| Citation, DOI | missing | `CITATION.cff`, Zenodo release hook | medium | S | PRD-31 |
| Paper pipeline | EVALUATION_PLAN | build from sources in CI | low | M | PRD-31 |

### 2.12 Legal and privacy

| Area | Evidence | Gap | Sev | Eff | Task |
|---|---|---|---|---|---|
| Privacy policy template, DPA notes | none | templates for self-hosters and hosted | high (blocker for hosted offering) | M | PRD-29 (human legal review) |
| Telemetry | opt-in telemetry mentioned in PL-03; semgrep documents it in `metrics.md` | Written policy, off by default, documented fields | medium | S | PRD-29 |
| LLM provider data handling | `docs/security/PROMPT_INJECTION.md` covers injection | Statement of what is sent to providers | medium | S | PRD-29 |

## 3. Top gaps (summary)

1. LICENSE and compliance files absent (PRD-01).
2. No SECURITY.md or disclosure process (PRD-03, PRD-02).
3. No CONTRIBUTING / CODE_OF_CONDUCT / issue forms (PRD-03, PRD-04).
4. No release pipeline: no tags, GHCR images, signatures, provenance, SBOM-on-release (PRD-13).
5. Containers run as root, no HEALTHCHECK, base images not digest-pinned, no image scan (PRD-08).
6. No SAST/CodeQL, Scorecard, dependency review (PRD-07).
7. No security headers or API rate limits (PRD-11).
8. API keys are static, unscoped, unhashed (IT-09, PRD-12).
9. No Helm chart, no upgrade guide, no config reference (PRD-16, PRD-17).
10. No docs site / Diataxis structure (PRD-18).
11. No browser e2e or accessibility automation (PRD-22, QS-12).
12. Threat model, tenant isolation and pen test not done (QS-01, QS-04, QS-03).
13. No SLOs/alerts/backups (QS-08, QS-11).
14. No published OpenAPI contract or API stability policy (PRD-15).
15. No privacy/telemetry/DPA pack (PRD-29).
