# Research notes: standards and exemplar repositories

Purpose: make `AUDIT.md` checkable. Every claim below was read from the cited page or API response. All accessed **2026-11-02**. Items not fetched or only partly fetched are marked **[unverified]**. Nothing here says Radius meets any standard; that judgement lives in `AUDIT.md` with repo evidence.

## 1. Standards

### 1.1 OpenSSF Scorecard
Source: https://raw.githubusercontent.com/ossf/scorecard/main/docs/checks.md

| Check | Risk | Notes (from source) |
|---|---|---|
| Binary-Artifacts | High | executables committed to repo |
| Branch-Protection | High | tiered up to 10: T1 no force-push/delete; T2 PR + 1 reviewer; T3 status checks; T4 two reviewers + code-owner review; T5 dismiss stale approvals, include admins |
| CI-Tests | Low | tests run on PRs |
| CII-Best-Practices | Low | badge: gold 10, silver 7, passing 5, in progress 2 |
| Code-Review | High | human review before merge; unreviewed human change -7 |
| Contributors | Low | >=3 orgs with >=5 of last 30 commits for top score |
| Dangerous-Workflow | Critical | untrusted checkout, script injection in Actions |
| Dependency-Update-Tool | High | Dependabot or Renovate |
| Fuzzing | Medium | OSS-Fuzz, ClusterFuzzLite or language fuzz/property tests |
| License | Low | LICENSE file (6), top level (3), OSI/FSF id (1) |
| Maintained | High | recent commits and issue activity |
| Packaging | Medium | published via workflow to a package hub |
| Pinned-Dependencies | Medium | hash/fixed-version pins in build/release |
| SAST | Medium | CodeQL, SonarCloud etc. |
| SBOM | Medium | exists (5) + published as release artifact (+5) |
| Security-Policy | Medium | SECURITY.md with contact (6), free text (3), disclosure text (1) |
| Signed-Releases | High | signature per release 8; SLSA provenance `*.intoto.jsonl` 10 |
| Token-Permissions | High | top-level read-only, write per job |
| Vulnerabilities | High | open known vulns per OSV |
| Webhooks | Critical | repo webhooks have secrets |

### 1.2 OpenSSF Best Practices badge
Sources: https://www.bestpractices.dev/en/criteria/0 (passing), /1 (silver), /2 (gold).
- **Passing** groups: Basics (FLOSS license in repo, docs, HTTPS site, discussion mechanism), Change Control (public VCS, unique version ids), Reporting (bug process, **published vulnerability reporting process, response within 14 days**, human-readable release notes listing fixed CVEs), Quality (working build, public automated test suite with instructions, policy to add tests for new functionality, linter), Security (no unpatched medium+ vulns older than 60 days, no leaked credentials, secure delivery), Analysis (static analysis before major release; dynamic analysis suggested).
- **Silver** (summary of fetched page): documented governance and roles, bus factor >= 2, coding standard enforced, DCO or CLA-like assertion, assurance case (threat model), hardening, >= 80% statement coverage, regression tests for >= 50% of recent bug fixes.
- **Gold** (summary of fetched page): silver first; >= 2 unassociated significant contributors; SPDX license id + copyright header in each source file; 2FA for committers; >= 50% of changes reviewed by non-author; reproducible build; 90% statement / 80% branch coverage; security headers on project site; security review within 5 years; dynamic analysis before major releases.
- Exact criterion ids were not captured. **[unverified]** whether silver/gold contain further items not summarised by the fetch tool.

### 1.3 GitHub community profile
Source: https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories
The fetched text lists README, CODE_OF_CONDUCT, LICENSE, CONTRIBUTING, and issue templates in `.github/ISSUE_TEMPLATE` with valid YAML front matter. It does not list the security policy or PR template as checklist items **[unverified: other GitHub docs pages may add them]**.

### 1.4 SLSA and Sigstore
- SLSA v1.0 Build track (https://slsa.dev/spec/v1.0/levels): L1 provenance exists; L2 hosted build platform + signed provenance, consumers verify; L3 hardened builds: isolated runs, signing secrets unreachable by user build steps.
- Sigstore keyless signing (https://docs.sigstore.dev/cosign/signing/overview/): OIDC identity, ephemeral key, Fulcio short-lived cert, Rekor transparency log. The page did not describe where registry signatures/attestations are stored **[unverified]**.
- Observed practice: pytest `deploy.yml` contains `id-token: write`, `attestations: write`, attest-build-provenance and PyPI `attestations: true` (see 2.2).

### 1.5 SBOM
- CycloneDX 1.7 (2025-10-21), OWASP + Ecma; covers SBOM, SaaSBOM, HBOM, VEX (https://cyclonedx.org/specification/overview/).
- CISA 2025 SBOM minimum elements: page only links a PDF; **field list not read [unverified]** (https://www.cisa.gov/resources-tools/resources/2025-minimum-elements-software-bill-materials-sbom).
- SPDX: **not fetched [unverified]**.

### 1.6 Project maturity
- CHAOSS (https://chaoss.community/kb-metrics-and-metrics-models/): Linux Foundation community-health project; 19 metrics-model articles, 89 metric articles; practitioner guides include Security, Responsiveness, Contributor Sustainability. Specific model names not confirmed.
- CNCF graduation criteria: the URLs tried returned 404; **not verified**. Do not cite CNCF criteria until fetched.

### 1.7 Versioning and commit conventions
- SemVer (https://semver.org/): MAJOR.MINOR.PATCH; 0.y.z is initial development, anything may change; public API must be declared; deprecation needs a MINOR release and removal in a later major.
- Keep a Changelog 1.1.0 (https://keepachangelog.com/en/1.1.0/): entry per version, newest first, dates, `Unreleased` section, types Added/Changed/Deprecated/Removed/Fixed/Security, state SemVer use.
- Conventional Commits 1.0.0 (https://www.conventionalcommits.org/en/v1.0.0/): `type(scope)!: desc`; fix=PATCH, feat=MINOR, breaking=MAJOR.

### 1.8 12-factor
https://12factor.net/ : Codebase, Dependencies, Config, Backing services, Build/release/run, Processes, Port binding, Concurrency, Disposability, Dev/prod parity, Logs, Admin processes.

### 1.9 OWASP
- API Security Top 10 2023 (https://api-security.owasp.org/editions/2023/en/0x11-t10): API1 BOLA, API2 Broken Authentication, API3 BOPLA, API4 Unrestricted Resource Consumption, API5 BFLA, API6 Unrestricted Access to Sensitive Business Flows, API7 SSRF, API8 Security Misconfiguration, API9 Improper Inventory Management, API10 Unsafe Consumption of APIs.
- ASVS: current stable 5.0.0 (May 2025) per https://github.com/OWASP/ASVS. Level definitions and chapter list could not be fetched (raw path 404). **Chapter/level mapping is unverified**; PRD-27 must map from the primary text.

### 1.10 Accessibility
WCAG 2.2 (https://www.w3.org/TR/WCAG22/): new AA criteria 2.4.11 Focus Not Obscured (Minimum), 2.5.7 Dragging Movements, 2.5.8 Target Size (Minimum), 3.3.8 Accessible Authentication (Minimum); A criteria 3.2.6 Consistent Help, 3.3.7 Redundant Entry; 4.1.1 Parsing removed. Relevant to Radius: the pannable graph visualizer (2.5.7), sign-in (3.3.8), small controls (2.5.8).

### 1.11 Docs, API, deploy
- Diataxis (https://diataxis.fr/): four forms, tutorials, how-to guides, technical reference, explanation. Detailed definitions were not on the fetched page.
- OpenAPI Specification latest 3.2.1 (10 Sep 2026) per https://spec.openapis.org/oas/latest.html. The OpenAPI version FastAPI emits was not checked **[unverified]**.
- Helm chart best practices (https://helm.sh/docs/chart_best_practices/): General Conventions, Values, Templates, Dependencies, Labels and Annotations, Pods and PodTemplates, CRDs, RBAC.

## 2. Exemplar repositories (GitHub API, read-only)

Data from `gh api repos/<r>`, `/contents`, `/contents/.github`, `/releases/latest` and workflow listings on 2026-11-02. Presence is by top-level and `.github` names only; absence means "not at the listed location", not "does not exist".

### 2.1 Table

| Repo | License | Stars | Root/`.github` table stakes seen | Release signal |
|---|---|---|---|---|
| danger/danger | MIT | 5.7k | CHANGELOG, VISION.md, Dockerfile, docs/, issue + PR templates, dependabot, Discussions on | v9.6.1, no assets (gem) |
| reviewdog/reviewdog | MIT | 9.7k | CHANGELOG, CONTRIBUTING (.github), PR template, renovate.json, goreleaser config + nightly, CodeQL, release workflow, Discussions on | v0.21.2, 10 binary assets |
| semgrep/semgrep | LGPL-2.1 | 17.4k | CHANGELOG + `changelog.d/` fragments, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY.md (email contact, supported versions table), CODEOWNERS, issue/PR templates, stale bot, AGENTS.md/CLAUDE.md, `metrics.md` (telemetry doc), `perf/`, nightly and e2e workflows | v1.183.0 |
| renovatebot/renovate | AGPL-3.0 | 23.0k | CODE_OF_CONDUCT, SECURITY.md, `.github/contributing.md`, DISCUSSION_TEMPLATE + ISSUE_TEMPLATE, `.releaserc.json` (semantic-release), `semantic.yml`, `check-commit-messages.yml`, `scorecard.yml`, `codeql-analysis.yml`, `dependency-review.yml`, PR size labeler, `docs/`, codecov, devcontainer, AGENTS.md | 44.201.1 (very high cadence) |
| pytest-dev/pytest | MIT | 14.7k | CHANGELOG.rst + `changelog/` fragments (chronographer.yml), CODE_OF_CONDUCT, CONTRIBUTING.rst, RELEASING.rst, SECURITY.md, AUTHORS, CITATION, FUNDING, .readthedocs, `doc-check-links.yml`, `prepare-release-pr.yml`, `deploy.yml` with attestations | 9.2.0 |
| getsentry/self-hosted | NOASSERTION (custom) | 9.6k | `install.sh`, docker-compose, `_integration-test`, `_unit-test`, `.craft.yml`, CHANGELOG, CONTRIBUTING, `enforce-license-compliance.yml`, release workflow, calendar versioning; Discussions off | 26.10.1 |
| plausible/analytics | AGPL-3.0 | 29.7k | CHANGELOG, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY.md, Makefile, `e2e/`, `all-checks-pass.yml`, public image build to GHCR, `terraform-e2e.yml`, `publish-docs.yml`, `migrations-validation.yml`, typos, FUNDING | v3.2.1 |
| PostHog/posthog | NOASSERTION (open core) | 40.6k | AGENTS.md/CLAUDE.md, AI_POLICY.md, CONTRIBUTING, CHANGELOG, CODEOWNERS + owners.yaml, renovate + dependabot, `.pinact.yaml` (action pinning), `.test_quarantine.json`, many Dockerfiles | frequent tagged sub-product releases |
| boxed/mutmut | BSD-3 | 1.5k | HISTORY.rst, ARCHITECTURE.rst, CONTRIBUTING.rst, readthedocs, e2e_projects | 3.8.0 |
| stryker-mutator/stryker-js | Apache-2.0 | 3.3k | MAINTAINERS.md, CODE_OF_CONDUCT, CONTRIBUTING, CHANGELOG, `perf/`, `e2e/`, renovate, stale bot | v10.1.1 |

### 2.2 Specific evidence used by the audit
- Scorecard run in CI: Renovate has `scorecard.yml` (workflow listing). Other repos checked did not list one.
- Provenance/attestation on release: pytest `deploy.yml` contains `attestations: write`, `id-token: write`, attest-build-provenance and PyPI `attestations: true` (grep of the decoded workflow).
- Security policy form: Semgrep SECURITY.md has a "Supported Versions" table and a reporting email (first 15 lines read). Minimal, but satisfies the Scorecard "contact" tier.
- Changelog fragments (towncrier-like): semgrep `changelog.d/`, pytest `changelog/`. Avoids merge conflicts on CHANGELOG.md.
- Telemetry transparency: semgrep ships `metrics.md` at root.
- License compliance gate in CI: Sentry self-hosted `enforce-license-compliance.yml`.
- Open-core split: Plausible and Renovate use AGPL-3.0; Sentry and PostHog show NOASSERTION (custom/mixed license files). The Radius licence is a human decision (QS-13).
- Docs deployment as a workflow: Plausible `publish-docs.yml`; pytest `doc-check-links.yml`.
- Self-hosting quality: Sentry install script + integration tests; Plausible `terraform-e2e.yml`.
- Stars and dates drift; they are as returned at fetch time.

### 2.3 Patterns distilled (used as criteria)
1. Mature repos have LICENSE, CONTRIBUTING, a security policy or private reporting path (semgrep, renovate, pytest, plausible: SECURITY.md), and a changelog.
2. Release automation is scripted (goreleaser, semantic-release, prepare-release PR, craft).
3. Contributor guardrails are automated: commit-message check, PR size labels, stale bot, link checking, typos.
4. Self-hosted products ship an install path that is tested in CI (Sentry, Plausible).
5. Telemetry is documented (semgrep `metrics.md`).
6. Agent-contributor policy files are appearing (AGENTS.md / CLAUDE.md / AI_POLICY.md in semgrep, renovate, posthog). Relevant to Radius, which verifies agent PRs.

## 3. Not fetched, so not relied on
CNCF graduation criteria, SPDX, ASVS level text, Docker/OCI best-practice pages, Kubernetes docs, GitHub private vulnerability reporting docs, CISA SBOM field list, reuse.software. Where the backlog needs them, the task's first step is to read the primary source.
