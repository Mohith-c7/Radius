# Product and Go-To-Market

**Status:** Proposed hypotheses to be tested with design partners (PL-06). Date: 2026-11-02.
Competitor facts below come from public pages and third-party reviews read on 2026-11-02; some sources are competitor or affiliate content, and funding/adoption claims are unverified. Re-verify before any external use. EP-01 (2026-11-02) re-checked the AgentProof, ScopeProof, Verik, SlopGate, TestSprite and Mutahunter rows against their repository/vendor pages; see `literature/related-work.md` section (d). The academic neighbours (SWE-ABS, AgentLens, etc.) are in `literature/`.

---

## 1. The problem (in the user's words)

Agentic teams push large volumes of code to GitHub. Nobody can read all of it, CI can pass while the tests are weak or were edited by the agent, and managers have no honest signal of how risky the merged code is.

## 2. Positioning (draft)

> **Radius turns every pull request into a checklist of what it must prove, and shows which parts are actually proven by evidence that would have caught a failure.**

Category claim: *evidence-based merge confidence for agent-written code.*

Not claimed: correctness guarantees, replacing CI, replacing reviewers, generating code.

## 3. Who it helps and how

| Persona | Pain today | What Radius gives them | Metric of value |
|---|---|---|---|
| **Developer using coding agents** | Agents say "done"; tests are green; hidden gaps appear in review or production | Criteria matrix in the PR, surviving-mutant and tamper findings, agent re-prompt, pre-push check via MCP | Fewer review round trips; defects caught before merge |
| **Reviewer / tech lead** | 4,000-line agent PRs; no idea where to look | "Review these first" list with reasons, per-criterion status | Review time per PR; defects found per hour |
| **Engineering manager** | No view of agent risk; vanity metrics | Calibrated trust trends by team/repo/agent tool; waiver and policy compliance | Post-merge defect rate vs predicted risk; verified share of agent PRs |
| **Security / compliance** | No audit trail for AI-written code | Auditable verdict justification, policies, waivers, logs | Audit readiness; policy compliance |
| **OSS maintainer** | Floods of low-quality AI PRs | Cheap deterministic gate (tamper rules, intent check) with explanations | Maintainer hours saved |

## 4. Competitive landscape

| Tool | What it is | Overlap | Radius' difference |
|---|---|---|---|
| **TestSprite** (company-reported: $6.7M seed Oct 2025 led by Trilogy Equity Partners, 35,000+ users; not independently verified) | AI generates and runs end-to-end tests (browser/API), MCP + CLI + GitHub Action, cloud execution, credits | Verifies agent code via tests, MCP distribution | Radius judges the **strength and coverage of evidence against intent**, works with any tests (including TestSprite's), is deterministic and self-hostable, and has a manager layer. Reported TestSprite limits: cloud-only, web/REST focus, false positives, unpredictable credit cost. |
| **PR-Agent (Qodo), CodeRabbit** | LLM PR review comments | PR surface | They give opinions; Radius gives auditable evidence and does not depend on an LLM for the verdict |
| **AgentProof** (github.com/RengGyu/AgentProof; name is shared by at least four unrelated repos) | Maps issue to acceptance criteria; a criterion is "met" only with linked passing execution evidence read from GitHub check metadata (does not run tests itself); deterministic, optional LLM adapter; short re-prompt. License not stated (no LICENSE file seen), 0 stars on 2026-11-02 | Closest conceptually | Radius adds evidence-quality (mutation, assertion strength, independence), tamper detection, calibration, process signals, manager layer. A different `GenRamzi/AgentProof` (Apache-2.0) re-runs tests on BASE/HEAD, uses fail-to-pass proof tests and integrity rules, and lists mutation as a future phase |
| **ScopeProof** (github.com/YuzeJ21/Scope-Proof) | Reviewer-confirmed criteria mapped to implementation/test candidates in a PR, evidence levels E0-E4, never executes PR code. Evaluation-only use policy, no OSS license | Criteria-to-evidence idea | Radius runs and scores evidence strength; ScopeProof is static candidate retrieval plus human acceptance |
| **Verik** (OSS, Apache-2.0 confirmed; TypeScript CLI, 23 deterministic checks incl. deleted tests and tautological assertions, runs build/tests) | CLI checking agent edits with deterministic rules | Tamper rules, snapshots | Radius links findings to intent and quantifies evidence strength; platform + dashboard |
| **SlopGate** (OSS, Apache-2.0 confirmed on PyPI; Python CLI and GitHub Action; test-tamper guard, phantom symbols, reproduction gate, slop-to-logic ratio) | AST checks for test tampering, hallucinated packages | Tamper rules | Same as above |
| **Mutation tools (Stryker, mutmut, PIT, Mutahunter)** (Mutahunter is AGPL-3.0: do not copy or link; the others were not re-checked) | Measure test strength | Ingredient | Radius scopes mutation to the changed symbols tied to criteria and turns it into a PR verdict |

Defensible differentiators (to be proven by the evaluation): (1) evidence-strength-aware criterion support (criterion-to-evidence mapping alone is not unique: AgentProof and ScopeProof do it), (2) evidence-quality weighting as a gold-free, PR-time predictor (benchmark-time test strengthening exists: SWE-ABS, UTBoost, PatchDiff), (3) calibrated trust with abstention, (4) process verification (process-aware evaluation of passing runs exists: AgentLens), (5) manager-level aggregate view, (6) self-hostable and deterministic. Differentiators 1 to 4 are hypotheses; see `literature/novelty-assessment.md`.

## 5. Product principles

1. **Evidence over opinion.** Every statement links to evidence ids.
2. **Honest uncertainty.** Intervals, "uncalibrated prior" labels, abstention.
3. **Fast first value.** Cheap signals in under two minutes; mutation async.
4. **Complement, not replace.** Ingest any tool's results; work with any test runner.
5. **Respect developers.** No individual surveillance by default; aggregate to teams/tools.
6. **Fail-open on the developer's machine; fail-closed on policy in CI** (configurable).

## 6. MVP definition (what to demo first)

MVP = M0 + M1 + M2 + M3 (about the first half of the plan):
- GitHub App comment with the criteria matrix, tamper findings, static assertion-strength, blast radius, honest verdict.
- Dashboard: intent panel, IEG viewer, evidence list.
- Advisory mode; policy file; CLI + Action.

Then M4 adds the headline feature (surviving mutants tied to criteria) and M5 adds calibration.

## 7. Go-to-market (hypotheses)

1. **Wedge:** teams already using Claude Code/Cursor/Codex heavily; individual developers via MCP/CLI and a free GitHub App for public repos.
2. **Distribution:** GitHub Marketplace; MCP directories; open-source rule packs and benchmark; the paper/preprint and a public leaderboard of "how much do agents' tests prove?".
3. **Land and expand:** developer installs for free -> tech lead sees review-time savings -> manager adopts portfolio view and policies -> enterprise gets self-hosted, SSO, audit.
4. **Content that sells:** demo repo with the four scripted PRs; case studies from design partners ("tests passed, but 40% of changed logic would not have been caught"); a short explainer of "plausible but passing" failures.
5. **Pricing (to test):** free for OSS/small teams; paid per active contributor or verified-PR volume with predictable pricing; metered managed-sandbox compute; enterprise self-hosted.

## 8. Success metrics

| Stage | Metric | Target (initial guess) |
|---|---|---|
| Activation | Time from install to first verdict | < 10 min |
| Engagement | Share of PRs where a finding led to a follow-up commit | > 25% |
| Quality | Reported false-positive rate | < 10% of findings |
| Trust | Calibration ECE on partner data | < 0.05 |
| Outcome | Post-merge defects in verified vs not-verified agent PRs | measurable difference |
| Retention | Teams still using after 8 weeks | > 60% of design partners |
| Research | Paper submitted with all RQs | by M7 |

## 9. Risks (product)

- Developers perceive friction or noise -> default advisory, tune rules, show only high-signal items first.
- Intent is missing in most real PRs -> templates, issue-link integration, `.radius/intent.yml` generator, prompts to the agent to write criteria.
- Mutation cost -> budgets, async, caching, optional managed compute.
- Large vendors add similar features -> speed, open benchmark, self-hosted, neutrality across agent tools.
- Misuse as surveillance -> aggregate-first design, role limits, documented ethics.
- Over-claiming -> language guide in PL-02; calibration displayed with intervals.

## 10. What users should see (acceptance for product value)

A new user can, within 10 minutes and without reading docs: install, open a PR, see "3 of 5 criteria proven, 1 weak (tests would miss changes to line 42), 1 unevidenced", click through to the evidence, copy an agent re-prompt, push a fix, and see the PR become verified.
