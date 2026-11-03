# First alpha release: go / no-go checklist

Scope: a tagged `v0.1.0-alpha` source release of Radius from this repository, for people who
build it locally. It is not a production or hosted release. Status as of 2026-11-03.

Legend: **DONE(verified)** = checked by running something or by a green CI run on develop;
**TODO** = engineering work not done; **OWNER** = only the repository owner can decide or do it.
Nothing here is ticked on trust.

## Go criteria

| # | Item | Status | Evidence / what is needed |
|---|---|---|---|
| 1 | develop CI, Coverage, Security, CodeQL, Smoke and Scorecard workflows green | DONE(verified) | Green on develop on 2026-11-03; Scorecard 7.4. Re-check on the release commit. |
| 2 | Local stack builds and runs healthy (`make dev`: migrations, api, worker, dashboard) | DONE(verified) | Run 2026-11-03. The worker image needed evidence+linking on `PYTHONPATH` (fix PR #119 must be in the release commit). |
| 3 | Browser run: sign-up, dashboard, demo sign-in, seeded analysis, real analysis with the Verdict v2 panel | DONE(verified) | Chrome, 2026-11-03. |
| 4 | Intent confirmation stores a new verdict revision (DEC-033) | DONE(verified) | Chrome, 2026-11-03. |
| 5 | End-to-end smoke (real API + worker + PostgreSQL + fake GitHub) | DONE(verified) | Linux CI runner. |
| 6 | README status, limitations and quickstart match what was verified | DONE(verified) | [README](../README.md), [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md). |
| 7 | Verdict v2 flag default stays `off`; `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS` stays `advisory` | DONE(verified) | Defaults read in `.env.example` and `docker-compose.yml` on 2026-11-03. Whether the release notes tell users to switch it on is an OWNER decision. |
| 8 | Secrets scan clean on the release commit | TODO | gitleaks runs in `security.yml` over full history (0 findings at the last recorded baseline). Re-run on the release commit and confirm `.env` is not tracked. |
| 9 | CHANGELOG entry for the release (fragments in `changelog.d/` compiled) | TODO | See [RELEASING](RELEASING.md). |
| 10 | Release notes say: alpha, static evidence, uncalibrated, live GitHub untested | TODO | Reuse the README status section. |
| 11 | "Re-run analysis", intent upload and JUnit upload buttons checked in the browser | TODO | Not verified; either check them or list them as untested in the notes. |
| 12 | Dashboard TypeScript typecheck, lint and build on the release commit | TODO | CI covers it; confirm the green run on the release commit. |
| 13 | License contributor consent: the second author's commits and consent to the Apache-2.0 grant | OWNER | PRD-01, [OWNER_ACTIONS](production-readiness/OWNER_ACTIONS.md). Do not publish before this is settled. |
| 14 | Capstone / sponsor IP question (whether the institution or sponsor has a claim) | OWNER | ALIGNMENT_LOG, DEC-018. A written answer is needed. The capstone files stay in the repository until the owner decides. |
| 15 | `SECURITY.md` contact placeholders replaced and private vulnerability reporting enabled | OWNER | PRD-02, OWNER_ACTIONS items 1-3 (also the conduct mailbox in `CODE_OF_CONDUCT.md`). A published repository with a dead security contact is a no-go. |
| 16 | GitHub App creation (permissions, webhook secret, private key) | OWNER | Needed only for live GitHub; the alpha can ship as "local only". Helper: `scripts/github_app_manifest.py`. |
| 17 | Webhook URL decision (public host, or no hosted instance for the alpha) | OWNER | No public URL exists and tunnels are not allowed. Blocks live-GitHub validation (F-06). |
| 18 | Live GitHub validation run | OWNER | Requires 16 and 17. Until done, release notes must say live GitHub is untested. |
| 19 | GitHub settings (branch protection, Discussions, labels) | OWNER | PRD-02, [branch protection](github-branch-protection.md). |
| 20 | Pre-registration freeze / deposit | OWNER | Not needed for the code alpha; needed before any research claim. |

## No-go (any one blocks the tag)

- Items 13, 14 or 15 unresolved.
- Any workflow in item 1 red on the release commit.
- Release notes or README claim anything listed as unverified in [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md).

## Out of scope for this alpha

Signed images and SBOM (PRD-13: `release.yml` exists but has never run and publishes nothing by default), Helm chart, published GitHub Action or CLI, SSO, production-mode
hardening sign-off, calibration, external security review.
