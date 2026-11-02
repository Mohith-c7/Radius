# Security Policy

Radius analyses untrusted code and text (pull requests, diffs, test reports, and, optionally, LLM output) and can execute tests in a sandbox. We take reports about it seriously.

## Reporting a vulnerability

Do **not** open a public issue, discussion or pull request for a suspected vulnerability.

**Primary channel: GitHub private vulnerability reporting.** Go to the repository's **Security** tab, choose **Report a vulnerability**, and fill in the advisory form. This creates a private advisory visible only to you and the maintainers.

> TODO-human: private vulnerability reporting must be enabled by the repository owner (Settings > Code security). This is tracked in PRD-02 (`docs/production-readiness/BACKLOG.md`). Until it is enabled, the "Report a vulnerability" button will not appear and the email fallback below is the only channel.

**Fallback: email** `security@<owner-configures-domain>`

> TODO-human: this is a placeholder, not a working address. The owner must create a monitored mailbox, replace the placeholder here, and say whether encrypted mail is supported. See `docs/production-readiness/OWNER_ACTIONS.md`, "Community files".

Please include: affected component and version or commit, a description and impact, reproduction steps or a proof of concept, and any suggested fix. Redact secrets and customer code from anything you send.

## Response targets

These are targets for a small, pre-1.0 project, not guarantees or a service-level agreement.

| Step | Target |
|---|---|
| Acknowledge your report | within 14 days (we aim for sooner) |
| Initial assessment (accepted, need more information, or declined, with reasons) | within 30 days |
| Fix or mitigation for confirmed high and critical issues | as soon as practical; we will share a plan and keep you updated |
| Public advisory | after a fix is available, coordinated with you; default disclosure window up to 90 days from the report, extendable by agreement |

We credit reporters in the advisory unless you ask us not to.

## Supported versions

Radius is pre-1.0 and has not published a stable release.

| Version | Supported |
|---|---|
| `develop` / `main` (latest) | Yes, security fixes land here |
| Any tagged release before 1.0 | Latest only, best effort |
| Older commits and forks | No |

This table will be updated when 1.0 is released.

## Scope

In scope (examples):

- **Sandbox escape or isolation bypass** in test execution (see `docs/security/EXECUTION_ISOLATION.md`). A sandbox escape is treated as **critical**.
- **Prompt injection that changes a verdict**: attacker-controlled PR text, comments, diffs or files that cause Radius (including its LLM-assisted parts) to produce a wrong, hidden or manipulated verdict, evidence or score (see `docs/security/PROMPT_INJECTION.md`). Verdicts are meant to be evidence-gated; any path that lets text from an untrusted source override evidence is in scope.
- Authentication, authorization and **cross-organization data access** in the API, worker and dashboard.
- Webhook signature handling, GitHub App token handling, and secret exposure in logs, responses or artifacts.
- Tampering with uploaded test evidence so that an unverified change is reported as verified.
- Supply-chain issues in this repository's build, CI workflows or published artifacts.

Out of scope (examples):

- Findings that need physical access, a compromised maintainer account, or a malicious operator of your own self-hosted instance.
- Denial of service by sending very large volumes of traffic; automated scanner output without a demonstrated impact; missing best-practice headers without an exploit.
- Social engineering of maintainers or users.
- Vulnerabilities in third-party dependencies that do not affect Radius; report those upstream (tell us if Radius is exposed).
- Bugs where Radius gives an unhelpful or imperfect verdict without an attacker (use the verdict report issue form instead).
- The legacy Gemini semantic pruner path. It is an experimental, advisory-only call-site classifier that is **not on the verdict path** (see the README). Ordinary bugs in it are welcome as normal issues, but it is not treated as a security boundary; a demonstrated way to make its output affect a verdict is an evidence-gating bypass and is in scope.
- A hosted service: none exists yet.

## Safe harbor

If you act in good faith to find and report a vulnerability under this policy, we will not pursue or support legal action against you for that research, and we will work with you to understand and fix the issue. Good faith means: you test only against your own installation or accounts; you avoid privacy violations, data destruction and service disruption; you stop and report as soon as you reach sensitive data and access no more than needed to demonstrate the issue; and you give us reasonable time to fix before disclosure. This statement is not a legal contract and does not authorize testing against systems you do not own. If in doubt, ask first through the channel above.

## No bug bounty

Radius does not run a bug bounty program and cannot offer payment. We offer credit and our thanks.
