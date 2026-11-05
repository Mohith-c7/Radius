# GitHub Branch Protection

Radius promotes code through three long-lived branches:

```text
feature/* | fix/* | docs/*  ->  develop  ->  dev (UAT)  ->  main
```

- `develop` is the default branch and the integration branch for daily work.
- `dev` is the UAT branch (DEC-005). The real branch is `dev`; older text calling it `uat` was wrong.
- `main` is the production release branch.

This page documents the configuration that is actually applied. It is applied by
`scripts/apply-github-branch-protection.ps1` (the owner runs it; the script is the
source of truth and this page mirrors it).

```powershell
$env:GITHUB_TOKEN = "<fine-grained token with Administration: write>"
.\scripts\apply-github-branch-protection.ps1
```

The script sets the default branch of `Mohith-c7/Radius` to `develop`, then
protects `develop`, `dev` and `main`.

## Rules common to `develop`, `dev` and `main`

- Pull requests are required; no direct pushes.
- Required status checks (names must match the workflow job names exactly):
  - `Validate` (`.github/workflows/ci.yml`)
  - `Python coverage` (`.github/workflows/coverage.yml`)
  - `Secret scan (gitleaks)` (`.github/workflows/security.yml`)
  - `Dependency audit (Python)` (`.github/workflows/security.yml`)
- Status checks are not "strict" (branches do not have to be up to date with the
  base before merging). Promotion PRs between long-lived branches would otherwise
  be stale after every merge.
- Force pushes are blocked.
- Branch deletion is blocked.
- All review conversations must be resolved before merging.
- Stale approvals are dismissed when new commits are pushed.
- Not required: signed commits, linear history, approval from someone other than
  the last pusher.
- `enforce_admins` is **false** (see below).

## Approvals per branch

| Branch | Approving reviews | CODEOWNERS review |
|---|---|---|
| `develop` | 0 | no |
| `dev` | 1 | no |
| `main` | 1 | yes (`.github/CODEOWNERS`) |

The solo owner is the only CODEOWNER and cannot approve their own pull request.
Until a second reviewer exists, the owner merges `dev` and `main` pull requests
by bypassing the review requirement as an administrator. The required status
checks still gate those pull requests unless the owner also overrides them,
which should not be done.

## Why these settings (and what was dropped)

An earlier version of this page and script demanded signed commits, linear
history, 2 approvals on `main`, and enforcement on administrators. That was never
applied, and it is unworkable for the current team:

- **Linear history forbids merge commits**, but promotion `develop -> dev -> main`
  is done with merge commits so each branch keeps the same commits.
- **Signed commits** would reject commits made by coding agents and tooling that
  have no signing key.
- **Two approvals on `main`** and **"approval from someone other than the last
  pusher"** cannot be met by a single owner, who cannot approve their own PR.
- **Enforcement on admins** would then lock the owner out completely.

## `enforce_admins = false`: when to tighten

The owner can bypass the rules as an administrator. This is deliberate: it is the
only way a solo owner can approve and promote. Tighten it (set `enforce_admins`
to true, raise `main` to 2 approvals, add `require_last_push_approval`) when a
second human reviewer or maintainer joins. Consider signed commits and linear
history only if the team moves to squash or rebase promotion and has a signing
setup for agents.

## Required check: Dependency audit (pnpm) is intentionally not required

The `Dependency audit (pnpm)` job passes only while the advisory baseline in
`.github/security/audit-baseline.json` is valid. Every baseline entry expires on
2027-01-31; after that the job fails by design until the baselines are reviewed.
Requiring it would block all merges on that date. It still runs on every pull
request and is reviewed manually. Add it to the required list only after the
baseline has been renewed or the advisories are fixed and the expiry is no longer
a risk.

## After the workflows have run

GitHub only offers a status check name for protection after it has reported at
least once. Re-run the script if a check name is rejected.

## Pull request template

`.github/pull_request_template.md` carries the Definition-of-Done checklist from
`docs/research/IMPLEMENTATION_PLAN.md` section 1.4, including the task ID and the
branch-flow target.
