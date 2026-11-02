# Radius GitHub Integration

GitHub App authentication, installation token exchange, PR comments, and Check
Run publishing for Phase 1 analysis results.


## Intent source ingestion (IN-02)

`radius_github.intent_*` fetches the pull request's intent (title, body, linked issues, commit messages, `.radius/intent.yml`) with a budgeted, read-only REST client and merges it into the analysis' intent snapshot. `radius_github.fake_api.FakeGitHub` is a stateful in-memory GitHub used by the tests (recorded-style responses in `tests/fixtures/api/`). Behavior, limits and open points: `packages/intent/README.md` (Source ingestion from GitHub) and `docs/github-app-validation/RUNBOOK.md` (section 6b).
