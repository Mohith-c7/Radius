# GitHub Branch Protection

This repository treats `dev` as the default integration branch and `main` as the
production release branch. Apply branch protection and set the default branch
with:

```powershell
$env:GITHUB_TOKEN = "<fine-grained token with Administration: write>"
.\scripts\apply-github-branch-protection.ps1
```

The script updates `Mohith-c7/Radius` so the default branch is `dev`, then
protects `dev` and `main` using GitHub's repository and protected branch APIs.

## Default Branch

- Default branch: `dev`
- Release branch: `main`
- Feature and work branches should target `dev` unless explicitly preparing a
  release promotion.

## `dev`

- Requires pull requests before merging.
- Requires 1 approving review.
- Dismisses stale approvals when new commits are pushed.
- Requires approval from someone other than the last pusher.
- Requires all review conversations to be resolved.
- Requires signed commits.
- Requires linear history.
- Applies rules to administrators.
- Blocks force pushes.
- Blocks branch deletion.

## `main`

- Requires pull requests before merging.
- Requires 2 approving reviews.
- Requires CODEOWNER review.
- Dismisses stale approvals when new commits are pushed.
- Requires approval from someone other than the last pusher.
- Requires all review conversations to be resolved.
- Requires signed commits.
- Requires linear history.
- Applies rules to administrators.
- Blocks force pushes.
- Blocks branch deletion.

## CI Checks

The branch-protection script requires the `Validate` GitHub Actions status check
from `.github/workflows/ci.yml`. Re-run the script after the workflow has run at
least once on GitHub so the check name is available to branch protection.
