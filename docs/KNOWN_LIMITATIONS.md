# Known limitations and open risks

Radius is an alpha. This page lists what is weak, missing or unproven, what reduces the risk
today, and where the fix is tracked. "Verified" means run by hand or by CI on 2026-11-03 (see the
status section of the [README](../README.md)); everything else is untested. Tracking ids point to
[production-readiness/BACKLOG.md](production-readiness/BACKLOG.md) (PRD-xx),
[research/tasks](research/tasks/) (task ids such as CA-xx, EV-xx, IN-xx) and
[research/ALIGNMENT_LOG.md](research/ALIGNMENT_LOG.md).

## 1. Verdict quality

| Limitation | Mitigation today | Planned fix / tracked in |
|---|---|---|
| **Static evidence only.** Verdict v2 rates tests by the shape of their assertions and by graph and name links. It does not check that a test would fail if the code were wrong. "Supported" is not "correct". | Wording says SUPPORTED, not proven; the alpha banner, `evidence_basis: static_only` and `calibrated: false` are in every v2 payload; the Check Run is advisory (`neutral`) by default (DEC-030). | Mutation-based evidence strength is wired behind `RADIUS_FEATURE_MUTATION` (default off, sandbox required, DEC-035): measured tests use a Wilson lower bound of their kill rate instead of the static cap. Bounded sample of one fault family, symbol-level links, synchronous in the analysis job; fixture sanity only ([MUTATION_WIRED.md](research/evaluation/MUTATION_WIRED.md)), RQ2 not run. |
| **Thresholds fitted to 8 fixtures.** `cap_static` 0.60 and `tau_support` 0.50 were chosen so the F-14 fixtures behave as designed. There is no held-out set, so no error rate (for example a false-verified rate) is known. | Parameters are versioned (`alpha-static` profile) and shown in each verdict; policy overrides have narrow ranges ([policy](policy.md)); the fixtures are regression tests only. | Held-out evaluation and calibration: CA-xx tasks, ALIGNMENT_LOG recommendation 4. See [verdict-v2.md](verdict-v2.md). |
| **Extraction recall is low by default.** The default `sections` mode reads only acceptance-style sections, checklists, Gherkin and spec files, so typical PR descriptions yield no criteria and the result is `insufficient_evidence`. | `RADIUS_INTENT_EXTRACTION_MODE=summary` (opt-in) proposes low-weight, never-confirmed criteria that block `verified` until confirmed (DEC-032); humans can add and confirm criteria in the dashboard; zero criteria never gives `verified` (DEC-031). | IN-09/IN-10 (gold set; real precision/recall numbers pending); IN-12 author prompts, not built. |
| **Author-controlled evidence.** The PR author writes the description, the criteria and the tests, and can add link hints. A motivated author can steer the verdict. | Hint edges that do not come from the base branch or a human confirmation are capped (DEC-030); tamper rules flag weakened or deleted tests; evidence is bound to the head SHA; `.radius/` policy and waivers are read from the base branch, with expiry. See the [threat model](security/VERDICT_V2_THREAT_MODEL.md). | Process verification and agent-authorship signals: PR-xx tasks; external review: PRD-30. Residual risk stays open. |
| **Linking quality unmeasured on real code.** Criterion-to-symbol and symbol-to-test linkers were evaluated on synthetic fixtures only; the 0-100 v1 score is an uncalibrated heuristic. | Reason codes and chain confidence are shown; weak links route to review. | LK-07 (link gold set), CA-xx. |
| **Python-first.** Verdict v2, tamper rules and symbol-level impact are Python only. TypeScript/JavaScript has dependency edges; Go, Java and Rust have symbols only. | Unsupported cases fall back to the full suite or `insufficient_evidence`. | Not scheduled. |
| **Test selection measured on a small corpus.** | Falls back to the full suite when the graph cannot map a change. | [benchmark](benchmarks/REAL_REPO_BENCHMARK.md); PRD-23. |

## 2. Platform and operations

| Limitation | Mitigation today | Planned fix / tracked in |
|---|---|---|
| **Live GitHub is untested.** Webhook delivery, GitHub App installation, installation tokens, rate limits, check runs and PR comments were exercised only against an in-memory fake (smoke test in CI). No public URL was available and tunnels are not allowed. | Webhook signature, replay and permission paths are covered by tests; a validation runbook exists. | F-06; [GitHub App validation runbook](github-app-validation/RUNBOOK.md); needs a deployed URL (owner). |
| **Production mode not run.** `docker compose up` without the dev override (https origins, real SMTP, managed API keys) was not run; the docs for it are derived from code and marked Unverified. | Compose files are checked statically (`scripts/check_compose.py`); production validation rejects unsafe settings. | PRD-25, PRD-17. See [INSTALL](operations/INSTALL.md). |
| **Dev-mode behaviours.** `make dev` auto-verifies accounts, prints sign-in links in logs, has one random dev API key, allows localhost CORS, and can load a demo login with a public password. | The dev override is a separate file; seeding refuses `RADIUS_ENV=production`; docs say never to expose it. | By design. |
| **No SSO/OIDC.** Password sign-in with e-mail verification only. | Sessions and API keys are hashed and scoped; see [HARDENING](operations/HARDENING.md). | PRD-26. |
| **No signed releases, images or SBOM.** Nothing is published; images are built from the checkout. | CI scans (CodeQL, dependency audit, image scan, gitleaks, Scorecard 7.4) run on develop. | PRD-13, PRD-14, PRD-32. See [RELEASING](RELEASING.md). |
| **No DAST and no external penetration test.** | SAST, dependency, secret and container scans in CI ([CI checks](security/CI_CHECKS.md)); HTTP hardening and tenant-isolation tests. | PRD-27, PRD-30, QS-03. |
| **Sandboxed test execution is experimental.** Off by default and fails closed; no penetration test; Windows sandbox tests not run. | [Isolation notes](security/EXECUTION_ISOLATION.md). | QS-03, F-07. |
| **Dashboard has no browser e2e or accessibility CI.** Not verified in this pass: the "Re-run analysis" button, the intent upload and JUnit upload buttons, and a TypeScript typecheck/lint/build run in this session (CI runs build checks on every PR). | A manual Chrome run of the main flows (README status). | PRD-22. |
| **Single maintainer, capstone origin.** Bus factor of one; a second author's commits and the capstone sponsor relationship are unresolved for licensing. | Apache-2.0 files are in the repository; DCO sign-off. | PRD-01 (owner); see [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md). |
| **Backup/restore, upgrade/downgrade and several worker replicas** are documented from code, not run. | Marked Unverified in the [operations docs](operations/README.md). | QS-11, PRD-28. |

## 3. Research

| Limitation | Mitigation today | Planned fix / tracked in |
|---|---|---|
| **Not pre-registered or frozen.** The pre-registration is a draft with no freeze commit, tag or archive deposit. Any result so far is exploratory. | The docs describe hypotheses, not results; the 2026-11 replay is labelled exploratory ([REPLAY](research/evaluation/REPLAY_2026-11.md)). | EP tasks; [PREREGISTRATION](research/preregistration/PREREGISTRATION.md); owner decision on deposit (PRD-31). |
| **Gold set has a single annotator.** The plan calls for two independent annotators with adjudication and at least 150 PRs; agreement cannot be measured with one. | Tooling and guidelines exist ([annotation](research/annotation/RUNBOOK.md)); no quality claim is made from the set. | IN-09, LK-07, EP-04. |
| **Calibration not done.** No reliability curve, and no abstention threshold justified by data. | Everything is labelled `heuristic_uncalibrated`. A tested measurement and guard toolkit exists but is not wired in and has seen no real labels ([CALIBRATION_TOOLKIT](research/evaluation/CALIBRATION_TOOLKIT.md)); it also records an open question about the loss in the pre-registration's conformal procedure. | CA-xx. |
| **Novelty not systematically reviewed.** | The README claims only what the [novelty assessment](research/literature/novelty-assessment.md) supports. | EP literature tasks. |
