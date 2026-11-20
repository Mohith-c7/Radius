# Trusted CI test evidence (P0.1)

Off by default. With `RADIUS_FEATURE_TRUSTED_EVIDENCE=true` (set it on the API **and**
the worker, DEC-041), Radius stores ordinary `/tests/results` uploads as `untrusted`
and diagnostic-only: they no longer re-score v1 confidence and Verdict v2 does not
count them. Only a report that is bound to the server-created manifest and its
report slot, uploaded by an approved GitHub Actions caller/reusable-workflow
identity, and verified as a GitHub Artifact Attestation can become
`verified_provenance`. Fork and manual analysis uploads remain diagnostic-only.
Verdict v2 remains advisory. With the flag off, the manifest and verified-results
routes answer 404 and every upload bound to the head commit counts as before.

Enabling the flag without every identity-policy setting leaves OIDC requests
denied; an unavailable GitHub API, GitHub CLI verifier or trust root yields
`unverifiable`, never a trusted score.

The attestation predicate type is `https://github.com/Mohith-c7/Radius/attestations/test-results/v1`. The reusable workflow signs with it and
the API verifier requires it (`radius_testing.provenance.PREDICATE_TYPE`); change
both together and bump the trailing version when the predicate fields change.

## GitHub requirements

For public repositories, Artifact Attestations are available on current GitHub
plans. Private or internal repositories require GitHub Enterprise Cloud; GHES
and unsupported plans do not have a supported private attestation flow. In
those cases Radius records evidence as unverifiable. See GitHub's [plan
requirements](https://github.com/actions/attest#usage), [private-repository
verification guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline),
and [GitHub CLI verifier](https://cli.github.com/manual/gh_attestation_verify).

The GitHub App installation needs `Attestations: read`, `Actions: read`, and
`Pull requests: read`. The called reusable workflow requires `contents: read`;
its attestation job additionally receives `id-token: write`,
`attestations: write`, `artifact-metadata: write`, and `actions: read`. Test
execution runs in an isolated job with no OIDC or write token.

Install the GitHub CLI on API hosts and keep its verification roots current.
The backend invokes `gh attestation verify` non-interactively against the
bundle retrieved through the GitHub App API; it does not depend on a logged-in
CLI session. A managed trusted root can be supplied with
`RADIUS_ATTESTATION_TRUSTED_ROOT_PATH`; refresh it using
`gh attestation trusted-root`. Preserve the root file through the deployment's
secret/config management rather than committing it. The API image installs the
official CLI at the `GH_VERSION` Docker build argument (default `2.103.3`);
upgrade it deliberately and validate both public and private roots before
deploying.

## Policy configuration

Set all values in [`.env.example`](../../.env.example) using the exact pinned
identities approved for the tenant:

- `RADIUS_ATTESTATION_REUSABLE_WORKFLOW` is the exact
  `owner/repository/.github/workflows/radius-trusted-evidence.yml@<full SHA>`
  value from the OIDC `job_workflow_ref` claim.
- `RADIUS_ATTESTATION_REUSABLE_WORKFLOW_SHA` is the full immutable SHA from
  `job_workflow_sha`.
- `RADIUS_ATTESTATION_CALLER_WORKFLOW_PATH` and
  `RADIUS_ATTESTATION_CALLER_WORKFLOW_SHA` pin the caller workflow path and
  its `workflow_sha` claim.
- `RADIUS_ATTESTATION_POLICY_VERSION` is recorded on each append-only
  verification event. Increment it on policy changes; prior evidence is not
  upgraded implicitly.

The helper source repository and revision are resolved from the signed
`job_workflow_ref` and `job_workflow_sha` OIDC claims, so the helper is checked
out from the same immutable Radius revision that defines the reusable workflow.
The called workflow obtains the manifest
using a job-scoped OIDC token, executes only server-selected pytest paths in a
separate no-token job, then attests and uploads one report for each authorized
slot. Supply the Radius analysis UUID and matching PR number from the analysis
that the workflow is verifying. This first adapter covers Python/pytest
reports; other test runners need a separately reviewed report adapter.

Example caller workflow. It assumes the repository already has a `radius-trigger`
job that exposes the corresponding analysis UUID as `outputs.analysis_id`.
Replace the repository name and pinned refs with the installation's values:

```yaml
jobs:
  radius-evidence:
    if: github.event_name == 'pull_request'
    needs: radius-trigger
    uses: Mohith-c7/Radius/.github/workflows/radius-trusted-evidence.yml@<FULL_RADIUS_SHA>
    with:
      analysis-id: ${{ needs.radius-trigger.outputs.analysis_id }}
      api-url: https://radius.example.com
      pull-request-number: ${{ github.event.pull_request.number }}
      python-version: "3.12"
```

The caller itself must be pinned by Radius policy. Do not populate `analysis-id`
from an untrusted PR body or upload request. The API verifies its repository,
owner, run, attempt, event, current PR head, analysis head and immutable
manifest against GitHub and SQL records.

## Local commands

Use the documented locked environment:

```powershell
uv sync --frozen --extra dev
corepack enable
pnpm install --frozen-lockfile
uv run --frozen python -m pytest apps/api/tests/test_provenance_auth.py apps/api/tests/test_attestation_verifier.py apps/api/tests/test_trusted_evidence_workflow.py
uv run --frozen python -m pytest packages/testing/tests/test_result_uploads.py packages/testing/tests/test_sqlalchemy_store.py packages/testing/tests/test_provenance_manifest.py apps/worker/tests/test_verdict_v2_collect.py packages/github/tests/test_verdict_v2_view.py packages/github/tests/test_verdict_v2_render.py
pnpm --filter @radius/dashboard test
pnpm --filter @radius/dashboard typecheck
pnpm --filter @radius/dashboard build
python scripts/export_openapi.py --check
```

To run the stack in PowerShell, use `pwsh -File scripts/dev.ps1 dev`. Keep the feature flag off
until a live GitHub Actions run has produced a report attestation and the
backend has verified both a public-repository and (where applicable) private
GitHub Enterprise Cloud bundle. This local workstation's inability to run a
GitHub-hosted workflow is not a reason to accept unsigned or unverified
results.
