# Phase 1 E2E Validation

This checklist verifies the full Phase 1 product loop after the API, worker,
database, dashboard, and GitHub App configuration are available in one
environment.

## Required Manual Inputs

- GitHub App id.
- GitHub App private key.
- GitHub webhook secret.
- Installation id for the test organization or repository.
- A test repository where pull requests can be opened safely.
- GitHub App permissions: contents read, pull requests read, checks read/write,
  issues write, metadata read.
- GitHub webhook events: `pull_request`, `push`, and `ping`.
- Dashboard runtime values:
  - `NEXT_PUBLIC_RADIUS_API_BASE_URL`
  - `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID`
  - `NEXT_PUBLIC_RADIUS_API_KEY`, when API-key enforcement is enabled.

## Preflight

1. Apply database migrations against the target database.
2. Start the API, worker, dashboard, and database.
3. Confirm API health from the same network as the dashboard.
4. Confirm the worker can claim and complete queued analysis jobs.
5. Confirm the dashboard can load repositories with the configured organization
   header.
6. Confirm the GitHub webhook endpoint rejects requests with an invalid
   signature.

## Happy Path

1. Install or configure the GitHub App for the test repository.
2. Connect the repository in Radius, or confirm the webhook path upserts it.
3. Open a pull request that changes at least one Python or TypeScript source
   file with an existing related test.
4. Confirm GitHub delivers a `pull_request.opened` webhook successfully.
5. Confirm Radius creates an analysis record with changed-file evidence.
6. Confirm the worker moves the analysis through queued, running, and completed
   states.
7. Confirm Radius persists:
   - changed files
   - dependency graph nodes and edges
   - blast-radius summary
   - selected tests and run plan
   - test execution result
   - confidence report and evidence
8. Open the dashboard analysis detail page.
9. Confirm the dashboard displays:
   - analysis status
   - repository and pull request identifiers
   - blast-radius counts
   - selected test count
   - dependency graph counts
   - confidence score, risk level, evidence, and recommendations
10. Re-run the analysis from the dashboard and confirm a new immutable analysis
    record is created.

## Failure Path

1. Open a pull request that causes a selected test to fail.
2. Confirm the worker completes the job with captured test output or marks the
   analysis failed with a clear reason.
3. Confirm the confidence report reflects the failed validation signal.
4. Confirm failed or risky analyses are visible in the dashboard overview and
   analysis detail page.

## GitHub Feedback Validation

Run these checks only after GitHub result publishing is configured.

1. Confirm Radius creates or updates a GitHub Check Run for the commit.
2. Confirm Radius posts a pull request comment with the confidence summary.
3. Confirm the GitHub output links back to the dashboard analysis page.
4. Push a second commit to the same pull request and confirm the previous
   feedback is updated or superseded without duplicating stale guidance.

## Acceptance Criteria

Phase 1 E2E is accepted when a real pull request can trigger Radius, complete
analysis through the worker, persist all core artifacts, display them in the
dashboard, and publish GitHub feedback when publishing credentials are enabled.

Record the validation date, environment, repository, pull request URL, analysis
id, and any known deviations in the release notes for the Phase 1 promotion.
