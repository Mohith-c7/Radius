# Contributing to Radius

Thanks for helping. Radius is a pre-1.0 project that verifies whether a pull request is safe to merge, so we hold our own changes to the same evidence-based standard. This guide is the practical path from clone to merged PR.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md), never in public issues. For questions see [SUPPORT.md](SUPPORT.md).

## Table of contents

1. [Ways to contribute](#ways-to-contribute)
2. [Development setup](#development-setup)
3. [Branch flow](#branch-flow)
4. [Commits and pull requests](#commits-and-pull-requests)
5. [Tests](#tests)
6. [Definition of Done](#definition-of-done)
7. [Review expectations](#review-expectations)
8. [How to add things](#how-to-add-things)
9. [AI-assisted contributions](#ai-assisted-contributions)
10. [Licensing and sign-off](#licensing-and-sign-off)

## Ways to contribute

- Report a bug, a wrong verdict (use the verdict report form) or a docs problem.
- Pick an issue labelled `good first issue` or `help wanted`.
- Propose a feature, a rule or an extractor (open an issue or a Discussion first for anything non-trivial).
- Improve tests, docs and benchmark cases.

Tasks are tracked in `docs/research/tasks/` and `docs/production-readiness/BACKLOG.md`. If you plan a larger change, say so in an issue first so we can agree on scope.

## Development setup

The full guide is [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). In short:

Prerequisites: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), Node.js (CI uses 22), pnpm 9.15.0 (pinned; enable via `corepack`), and optionally GNU make. Windows users can use `scripts/dev.ps1` instead of make.

```bash
git clone https://github.com/<your-fork>/Radius.git && cd Radius
make setup        # uv sync --frozen --extra dev, corepack enable, pnpm install
make dev-local    # API + worker + dashboard natively, in-memory storage
make dev          # or: the full Docker stack (Postgres, API, worker, dashboard)
make test         # python -m pytest
make lint         # ruff
```

PowerShell equivalent: `.\scripts\dev.ps1 help` lists every target. `make help` lists the make targets.

Never commit `.env` files or real tokens. New settings go into `.env.example` as placeholders only.

## Branch flow

Radius uses a promotion flow (DEC-005 in [docs/decisions.md](docs/decisions.md)):

```text
feature/* | fix/* | docs/*  ->  develop  ->  dev (UAT)  ->  main (release)
```

- Fork or branch from the latest `develop`, with a short-lived branch named `feature/<area>-<summary>`, `fix/<summary>` or `docs/<summary>`.
- Open pull requests **against `develop`**. Do not target `dev` or `main`.
- Never commit directly to `dev` or `main`, and never push test or throwaway commits to them.
- Promotion `develop` -> `dev` -> `main` is done only by the owner after a milestone gate. Hotfixes start from `main` and are merged back to `main`, `dev` and `develop`.
- One task, one branch, one PR. Never force-push shared branches.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat(intent): ...`, `fix(api): ...`, `docs(readme): ...`, `test(graph): ...`, `ci(security): ...`, `chore: ...`. Use the package or area as the scope.
- Put the task ID (for example `IN-03` or `PRD-04`) in the PR title and body.
- Keep PRs reviewable: about 600 changed lines or fewer, excluding generated files and fixtures. Split larger work.
- Fill in the PR template: summary, the exact commands you ran with their results, Definition of Done checklist, and screenshots for UI changes.
- Do not expand scope. Write down follow-ups instead of folding them in.

## Tests

- Python: `make test` (or `uv run --frozen python -m pytest`). Dashboard: `pnpm test`. Lint and types: `make lint`, `pnpm lint`, `pnpm typecheck`.
- Every feature needs unit tests and, where it crosses components, an integration test. Coverage targets are in the development guide (backend 90 percent, frontend 80 percent, critical services 100 percent).
- Never weaken, skip or delete a test to get green. Radius exists to catch exactly that, and reviewers will check.
- Tests must be deterministic. Quarantine or fix flaky tests (see `docs/FLAKY_TESTS.md`) rather than retrying them.
- Tests that need hostile payloads run only in the sandbox (`-m sandbox_adversarial`); LLM tests use deterministic stub models and no network.
- Every new table or endpoint needs an organization-isolation test (tenant A must not read tenant B).

## Definition of Done

Adapted from `docs/research/IMPLEMENTATION_PLAN.md` section 1.4. Your PR is ready when:

- [ ] Acceptance criteria are met and demonstrable.
- [ ] Unit tests plus at least one integration test; new paths covered; no flaky tests.
- [ ] Lint, typecheck and build pass locally and in CI.
- [ ] DB changes have an Alembic migration, a downgrade path and an upgrade test.
- [ ] API changes update `docs/API_CONTRACTS.md` and the OpenAPI schema.
- [ ] New settings are in `.env.example` (placeholders) and `docs/DEPLOYMENT.md`.
- [ ] Computed outputs carry `algo_version` and are deterministic for the same input.
- [ ] Risky or new behavior sits behind a feature flag (`RADIUS_FEATURE_<NAME>`) until its gate passes.
- [ ] Docs are updated (module README, `docs/` page, task checkbox).
- [ ] No secrets, tokens, customer code or personal data in code, logs, fixtures or tests.
- [ ] The security checklist (`IMPLEMENTATION_PLAN.md` section 6) is reviewed if you touch untrusted input, execution, auth or LLMs.

## Review expectations

- Expect a first response within a few days; this is best effort, not a guarantee.
- CI must be green before review. A maintainer reviews for correctness, tests, scope and docs. The owner decides ties.
- Review comments are about the code. Be kind, answer in the thread, and push follow-up commits rather than force-pushing during review.
- Claims need evidence: link the test, the benchmark output or the doc. We avoid unsupported words such as "best" or "guaranteed".
- Changes to verdict logic, scoring, the sandbox or prompts get extra scrutiny and may be asked to include benchmark results.

## How to add things

### A benchmark case (intent-to-evidence fixture)

Golden fixtures live in `benchmarks/fixtures/intent/NN_<name>/`, each with `README.md`, `intent.md`, `base/`, `head/`, `pr.patch` and `expected.json`. `expected.json` must validate against `benchmarks/fixtures/intent/expected.schema.json`. The tests in `benchmarks/test_intent_fixtures.py` re-run the claimed outcomes with real pytest runs and check that `pr.patch` equals the regenerated diff. Copy the closest existing fixture, change it, and run `uv run --frozen python -m pytest benchmarks`. Dataset manifests for external datasets are in `benchmarks/datasets/manifests/` (schema: `manifest.schema.json`); read `docs/research/datasets/DATA_HYGIENE.md` before adding one. Never add private code or personal data.

### An intent criterion extractor

Deterministic extractors live in `packages/intent/src/radius_intent/infrastructure/extraction/`; the package README explains the ports (`CriterionExtractor`) and invariants. Keep extractors deterministic and LLM-free unless you are working on the guarded, default-off LLM extractor (it must pass the prompt-injection guard in `radius_shared.llm_guard`). Add fixtures and unit tests, and bump the extractor version if output changes.

### A language parser extractor

Parsers live in `packages/parser/src/radius_parser/extractors/` (one module per language: `python.py`, `typescript.py`, `go.py`, `java.py`, `rust.py`). Add or extend the module, add tests under `packages/parser/tests/`, and update the README capability statement honestly (experimental languages stay labelled experimental).

### A rule

Rule packs are planned (see `docs/research/PRODUCT_AND_GTM.md`) but there is no stable rule format yet. Open a "Rule or extractor proposal" issue first so the shape can be agreed before code is written.

## AI-assisted contributions

AI-generated or AI-assisted pull requests are welcome under the same rules as any other. You are responsible for what you submit: read and understand every line, run the tests yourself, and do not paste unreviewed output. Disclose significant AI assistance in the PR description. Agents must also follow [AGENTS.md](AGENTS.md). We may close PRs that look like unreviewed bulk output.

## Licensing and sign-off

### License of contributions (inbound = outbound)

Radius is licensed under the Apache License 2.0 (`LICENSE`, `NOTICE`; decision DEC-018 in `docs/decisions.md`). By submitting a contribution you agree that it is licensed to the project and to everyone who receives the project under the same Apache License 2.0 ("inbound = outbound"), as set out in section 5 of that license. You keep your copyright. You also confirm you have the right to submit the work: it is your own, or you have your employer's or institution's permission, or it comes from a source whose license allows inclusion under Apache-2.0.

Practical rules:

- Do not copy code, rules, prompts or data from other projects unless the license is compatible with Apache-2.0 and the source and license are recorded in `NOTICE` or `THIRD_PARTY_NOTICES.md`. In particular, do not copy or vendor code that is AGPL/GPL/SSPL, source-available (for example BSL/FSL), or has no license (no license means all rights reserved). See `docs/research/literature/related-work.md` for the licenses of related tools.
- Do not commit third-party datasets or their rows. Only manifests, hashes and fetch scripts belong in the repo (`docs/research/datasets/DATA_HYGIENE.md`).
- New dependencies must pass the license gate (`scripts/ci/license_check.py`, run by the `sbom-licenses` job in `.github/workflows/security.yml`): strong copyleft (AGPL, SSPL, GPL) is blocked, weak copyleft (LGPL, MPL) is reported and allowed when used as an unmodified library.

### Sign your commits (DCO)

We use the Developer Certificate of Origin (https://developercertificate.org/), not a Contributor License Agreement (CLA). Add a sign-off line to every commit:

```
git commit -s -m "feat(intent): describe the change"
# adds: Signed-off-by: Your Name <you@example.com>
```

The sign-off states that you wrote the change or have the right to submit it under the project license. Why DCO and not a CLA:

- A DCO is lightweight: no legal document to sign, no tooling or account, and it does not transfer or broaden any rights. Contributors keep their copyright and the license grant comes from Apache-2.0 section 5 itself.
- A CLA that assigns or broadly relicenses rights discourages contributors and enterprise employees, and a CLA signing flow is operational overhead we do not need now.
- Trade-off: with a DCO and contributors who keep their copyright, the project cannot later relicense contributed code without asking each contributor. That is accepted on purpose (it is also a trust signal: the open core stays open). Proprietary enterprise features are written as separate modules, not by relicensing contributed code (DEC-018).

Status: the DCO is recommended now and will be enforced by a CI check (for example the DCO GitHub App) once there are external contributors. Until then, a missing sign-off is not a reason to reject a change from the maintainers.

Security reports go through `SECURITY.md`, never a public issue.
