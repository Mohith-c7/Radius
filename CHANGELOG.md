# Changelog

All notable changes to Radius are recorded here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Versioning is intended to follow [Semantic Versioning](https://semver.org/); `0.y.z` means anything may change.

Radius is pre-1.0. `pyproject.toml` and `package.json` say `0.1.0`, but no release has been cut and no git tag exists, so everything below is under **Unreleased**. The entries are reconstructed from the git history of `develop` and the task identifiers in commit messages (F-, IN-, QS-, EP-, P1 to P3 and phase labels refer to the plans under `docs/`). They describe what the repository contains, not a supported product.

New entries come from fragments in [`changelog.d/`](changelog.d/README.md); see [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

### Added

- Monorepo foundation: FastAPI API, durable analysis worker, Next.js dashboard, and the `analysis`, `confidence`, `github`, `graph`, `parser`, `repository`, `shared` and `testing` packages, with an Alembic-managed PostgreSQL schema.
- Code analysis: Python parsing with the standard-library `ast`; TypeScript/JavaScript parsing with tree-sitter and `tsconfig`-aware import resolution; tree-sitter symbol extraction for Go, Java and Rust (experimental, no import resolution); a code graph with unified-diff hunk mapping.
- Conservative Python symbol-level impact analysis feeding test selection and blast radius, behind `RADIUS_FEATURE_SYMBOL_IMPACT` (F-08), with a ground-truth comparison test.
- Graph-driven test selection with a full-suite fallback, and CLI command export.
- Evidence ingestion: JUnit XML and JSON results bound to the analysed head commit, accumulated across uploads, and counted only when they cover the selected tests; evidence-gated verdicts `verified`, `failed` and `insufficient_evidence` (P1, P2).
- GitHub App integration: signed webhooks, `Radius confidence` check runs, PR comments with blast-radius tables, repository sync on installation, handling of installation removal.
- Dashboard: repository, pull request and analysis pages, interactive graph visualiser, test selection hub, report ingestion, and Intent panel with criteria confirmation (IN-11). Email/password and Google/GitHub OAuth sign-in.
- Optional sandboxed test execution that fails closed when its runtime is unavailable, with an adversarial test suite (F-07). Off by default.
- Flaky-test detection, a rerun policy and quarantine listing; a flaky test counts as a failure.
- Intent layer through milestone M1: domain model (IN-01), deterministic criterion extraction and `.radius/intent.yml` schema (IN-03), optional guarded LLM extraction (IN-04), testability rating (IN-05), versioned snapshots (IN-06), persistence migration (IN-07), intent API (IN-08), and wiring of the deterministic rater and gated LLM extractor into the API.
- LLM input/output guard and a prompt-injection test corpus with stub models (QS-02).
- Observability baseline with optional tracing and metrics, and trace propagation from API to worker (F-10).
- One-command development environment, Compose profiles and opt-in demo seed data (`make dev`, `scripts/dev.ps1`) (F-15).
- CI: lint, typecheck, tests and build (`ci.yml`), coverage gate (`coverage.yml`), secret scan, dependency audits, SBOM and licence policy (`security.yml`), nightly benchmarks (`nightly.yml`) (F-13, QS-05).
- Benchmarks: reproducible mutation benchmark with independent ground truth (P3), a self-evaluation report on Radius's own packages, and a golden intent-to-evidence fixture corpus (F-14).
- Research track documents: design, implementation and evaluation plans, literature review and novelty assessment (EP-01), pre-registration draft (EP-02, not frozen), pinned dataset manifests and tooling (EP-03), and recorded decisions DEC-006 to DEC-025.
- Production-readiness audit, backlog and research notes under `docs/production-readiness/`.
- Conventional Commits check for pull requests (`scripts/ci/commit_lint.py`, `.github/workflows/commit-lint.yml`), this changelog and the `changelog.d/` fragment directory (PRD-06).

### Changed

- The 0-100 confidence score is labelled `heuristic_uncalibrated` in the API, PR comment, check run and dashboard (F-02).
- The job queue is a PostgreSQL table; README and deployment documentation no longer mention Redis (F-02).
- The experimental LLM semantic pruning step is not part of the analysis pipeline, so no model output can remove tests from the selection (see `docs/audit/RADIUS_AUDIT.md`).
- README and deployment guide aligned with the code (F-02); README restructured with maturity labels and a status section (PRD-05). Branch flow documentation reconciled to `feature/* | fix/* | docs/* -> develop -> dev -> main` (F-04, F-16).
- Generated artifacts untracked and a stale audit script removed (F-03).

### Fixed

- Database migrations run on container start; the missing coverage migration and model registration were added.
- Deployment honours the `PORT` variable and normalises PostgreSQL database URLs; the API receives `GITHUB_SINGLE_TENANT` and the webhook URL documentation was corrected.
- GitHub integration defects: the real default branch is used, an in-progress check run is published at job start and is never left stuck, queued analyses are cancelled when a pull request closes, and `git clone` authenticates with Basic `x-access-token` without exposing the token on argv or in git config.
- Settings and tests no longer depend on a local `.env`; the lockfile was refreshed.
- Dynamic CORS origins from environment variables; first-run failures in the coverage and gitleaks workflows.

### Security

- Dashboard API calls are proxied server-side so `RADIUS_API_KEY` never reaches the browser (F-05).
- Container test sandbox hardened and fail-closed (F-07).
- Path traversal and LLM prompt-injection flaws patched in the early analysis pipeline; symlink traversal mitigated when reading repositories.
- XML entity expansion defused in the JUnit parser.
- Untrusted intent text is sanitised before storage and is never executed; intent routes return 404, not 403, for another organization's analysis.
- CI hardening: least-privilege workflow tokens, actions pinned by commit SHA, gitleaks on full history, blocking `pip-audit`, `pnpm audit` with an expiring baseline, and a licence gate against AGPL/SSPL/GPL dependencies.
- Unsigned webhooks and keyless API calls are accepted only when `RADIUS_ENV` is `development` or `test` and `RADIUS_ALLOW_INSECURE_DEV` is set.
