## Summary

<!-- What changed and why. -->

Task ID(s): <!-- e.g. F-04, IN-03 -->

## Branch flow

- [ ] This PR targets `develop` (`feature/*`, `fix/*`, `docs/*`), or it is an owner promotion (`develop` -> `dev` -> `main`).
- [ ] No direct commits to `dev` or `main`; no test or throwaway commits.

## How it was tested

<!-- Commands you ran and their results. -->

## Definition of Done

(from `docs/research/IMPLEMENTATION_PLAN.md` section 1.4; delete lines that do not apply and say why)

- [ ] Acceptance criteria in the task are met and demonstrable.
- [ ] Tests: unit tests plus at least one integration test; new code paths covered; no flaky tests; no tests weakened, skipped or deleted to get green.
- [ ] Lint, typecheck, `pnpm lint` and build pass locally and in CI.
- [ ] DB changes have an Alembic migration, a downgrade path and an upgrade test; new tables/endpoints have an org-isolation test.
- [ ] Docs updated (module README, `docs/` page, API contracts if the API changed, task checkbox ticked in the task file).
- [ ] Changelog: added a changelog entry or fragment if the project has a changelog for this change (otherwise write "n/a").
- [ ] Tests: listed the new or changed tests, or explained why none apply.
- [ ] No secrets, tokens, customer code or PII in code, logs, fixtures or test data; new settings are in `.env.example` as placeholders only.
- [ ] Risky or new behavior is behind a feature flag (`RADIUS_FEATURE_<NAME>`) until its milestone gate passes.
- [ ] Computed outputs carry `algo_version` and are deterministic; Research hook output recorded if the task has one.
- [ ] Security checklist (`IMPLEMENTATION_PLAN.md` section 6) reviewed if this touches untrusted input, execution, auth or LLMs.
- [ ] PR is reviewable in size (about 600 changed lines or fewer excluding generated files), or split.

## Screenshots (UI changes)

<!-- Optional. -->
