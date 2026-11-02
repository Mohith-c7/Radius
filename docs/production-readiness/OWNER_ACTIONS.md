# Owner actions

Things only the repository owner can configure. Each section is self-contained.

## Community files

Added by PRD-03 and PRD-04. Nothing here is guessed: every item is a placeholder the owner must fill in.

| # | Action | Where |
|---|---|---|
| 1 | Enable GitHub private vulnerability reporting (Settings > Code security). Tracked in PRD-02. Until then the "Report a vulnerability" link in `SECURITY.md` and the issue chooser does not work. | GitHub settings |
| 2 | Create a monitored security mailbox and replace `security@<owner-configures-domain>` in `SECURITY.md`. Decide whether encrypted mail is supported and say so. | `SECURITY.md` |
| 3 | Create a monitored conduct mailbox and replace `conduct@<owner-configures-domain>` in `CODE_OF_CONDUCT.md` (may be the same mailbox as item 2). | `CODE_OF_CONDUCT.md` |
| 4 | Enable GitHub Discussions with categories Q&A, Ideas and Show and tell (slugs `q-a`, `ideas`, `show-and-tell`, matching `.github/DISCUSSION_TEMPLATE/`). The discussions link in `.github/ISSUE_TEMPLATE/config.yml` returns 404 until then. | GitHub settings |
| 5 | Apply `.github/labels.yml` once (no sync workflow is installed), for example with a label-sync tool run by the owner. Issue forms reference these labels; GitHub silently drops labels that do not exist. | GitHub labels |
| 6 | Confirm the maintainer list in `MAINTAINERS.md` and the single-owner governance in `GOVERNANCE.md`. | those files |
| 7 | When the license lands (PRD-01, branch `chore/license-apache-2.0`), reconcile the "Licensing and sign-off" section of `CONTRIBUTING.md` with the DCO text on that branch. | `CONTRIBUTING.md` |
| 8 | The issue-chooser links use `Mohith-c7/Radius` and the `develop` branch. If the repository is renamed or moved, or the default branch changes, update `.github/ISSUE_TEMPLATE/*` and `SUPPORT.md`. | those files |
