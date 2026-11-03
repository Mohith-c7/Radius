# Radius Implementation Plan (Research + Product)

**Status:** Proposed. Date: 2026-11-02. Verification note 2026-11-03: the dev stack, the Verdict v2 panel and intent confirmation (DEC-033) were run in Chrome and the smoke test passes in CI; real GitHub, production mode, calibration, mutation scores in the worker and a second annotator remain unverified (see [KNOWN_LIMITATIONS](../KNOWN_LIMITATIONS.md)). Task boxes below were not changed by that pass.
**Companion docs:** `DESIGN.md` (what and why), `EVALUATION_PLAN.md` (paper track), `PRODUCT_AND_GTM.md` (market track), `tasks/*.md` (the detailed tasks).

This plan has **three tracks that run together** and share one codebase:

| Track | Goal | Where |
|---|---|---|
| **Engineering** | Build the intent-to-evidence verification platform | `tasks/F-`, `IN-`, `LK-`, `EV-`, `VD-`, `PR-`, `CA-`, `TR-`, `MG-`, `IT-`, `QS-` |
| **Research** | Produce a publishable paper with defensible results | `EVALUATION_PLAN.md` (tasks `EP-xx`) |
| **Product / market** | Ship something users adopt and pay for | `tasks/PL-product-launch.md`, `PRODUCT_AND_GTM.md` |

Every engineering task has a **Research hook** (what to log so the paper can use it) and, where relevant, a **Product hook** (what the user sees).

---

## 1. Rules for everyone (humans and AI agents)

### 1.1 Before you start any task
1. Read `docs/AI_CONTEXT.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/research/DESIGN.md`, and your task's file. Read `docs/audit/RADIUS_AUDIT.md` for known gaps.
2. Confirm every dependency listed in the task is merged into `develop`. If not, stop and report; do not stub around it silently.
3. Verify repo paths named in the task still exist (they come from the 2026-11-01 audit).

### 1.2 Branching (non-negotiable)
- Flow: `feature/* | fix/* | docs/*  ->  develop  ->  dev (UAT)  ->  main (production)`.
- **Never commit directly to `dev` or `main`.** Never push test or throwaway commits to `dev` or `main`.
- Branch name: the task's `Branch:` field (`feature/<area>-<summary>`), created from the latest `origin/develop`.
- One task = one branch = one PR into `develop`. Large tasks may be split into sub-PRs, but each must leave `develop` green.
- Promotion `develop -> dev -> main` is done only by an owner, after the milestone gate (section 4).
- Note: `docs/DEVELOPMENT_GUIDE.md` calls the UAT branch `uat`; the team's actual branch is `dev`. Task F-04 reconciles this.

### 1.3 Commits and PRs
- Conventional commits (`feat(intent): ...`, `fix(api): ...`, `docs(research): ...`, `test(...)`, `ci(...)`).
- PR description must include: task ID(s), what changed, how it was tested, Research hook output, screenshots for UI, and a checklist of the Definition of Done.
- Do not squash away the task ID. Include it in the PR title.

### 1.4 Definition of Done (every task)
- [ ] Acceptance criteria in the task are all met and demonstrable.
- [ ] Unit tests + at least one integration test; new code paths covered; no flaky tests.
- [ ] `ruff`/lint, typecheck, `pnpm lint`, build pass locally and in CI.
- [ ] DB changes have an Alembic migration, a downgrade path, and a test that upgrades from the previous head.
- [ ] Every new table/endpoint has an **org-isolation test** (tenant A cannot read tenant B).
- [ ] API changes update `docs/API_CONTRACTS.md` and the OpenAPI schema.
- [ ] Any new setting is in `.env.example` (placeholder only, never a real secret) and `docs/DEPLOYMENT.md`.
- [ ] Computed outputs carry `algo_version`, are deterministic for the same input, and are logged for research (see the Research hook).
- [ ] New behavior sits behind a feature flag (`RADIUS_FEATURE_<NAME>`) until its milestone gate passes.
- [ ] Docs updated (module README, `docs/` page, task checkbox ticked in the task file).
- [ ] No secrets, tokens, customer code or PII in logs, fixtures or test data.
- [ ] Security checklist (section 6 of this file) reviewed if the task touches untrusted input, execution, auth or LLMs.

### 1.5 Extra rules for AI coding agents
- Do not expand scope. If you find a needed change outside the task, open a note in the PR and create a follow-up task entry; do not do it silently.
- Do not weaken, skip or delete tests to get green. (Radius exists to catch exactly that.)
- Do not invent facts about repo state: run commands and read files.
- Keep each PR reviewable (target under about 600 changed lines excluding generated files and fixtures; split otherwise).
- When a task says "decision needed", stop and ask the owner; do not choose.
- Record the commands you ran and their results in the PR description.

### 1.6 Research logging rule
Anything the paper might cite must be reproducible. Store inputs, config, `algo_version`, seeds and outputs via the mechanisms in `DESIGN.md` section 9. If a task changes an algorithm, bump `algo_version` and keep the old implementation selectable until the evaluation freezes.

---

## 2. Task template (used in every `tasks/*.md`)

```
### <ID> <Title>                                       [ ] not started  [~] in progress  [x] done
- Owner type:   agent-ok | human-required | pair (agent implements, human reviews decision)
- Depends on:   <task IDs>
- Branch:       feature/<area>-<summary>
- Size:         S (<1d) | M (1-3d) | L (3-5d) | XL (split it)
- Goal:         one sentence
- Scope / steps: numbered, concrete (files, functions, endpoints, tables)
- Out of scope: what must NOT be done here
- Acceptance:   checkable statements
- Tests:        what must exist
- Research hook: what to record for the paper
- Product hook:  what the user sees / value
- Risks / notes
```

---

## 3. Phases and dependency overview

```
F  Foundations & hygiene  ----------------------------------------------+
|                                                                         |
+--> IN Intent layer --> LK Linking --> EV Evidence quality --> VD Verdict v2 --+--> CA Calibration
|                                          ^                       ^            |
|                                          |                       |            +--> TR Triage --> MG Manager
+--> PR Process verification (needs F, feeds VD/CA) -----------------+            |
                                                                                   +--> IT Integrations (parallel from VD)
QS Quality/Security/Ops runs continuously;  PL Product/Launch runs continuously;  EP Evaluation runs continuously
```

Critical path for the **paper**: F -> IN -> LK -> EV -> VD -> CA, plus EP-xx datasets in parallel from the start.
Critical path for the **product MVP**: F -> IN -> LK -> EV (tamper + static first) -> VD -> IT (Action + comment) -> PL (onboarding).

---

## 4. Milestones and gates

Durations are suggestions for a small team; adjust to the real calendar. A milestone is "done" only when its gate passes; promotion to `dev` happens at the gate.

| M | Name | Includes | Gate (must all be true) |
|---|---|---|---|
| **M0** | Stabilize | F-01 to F-15 | CI green; sandbox proof tests pass; live GitHub App test done; README matches code; repo hygiene clean; branch flow doc fixed |
| **M1** | Intent MVP | IN-01 to IN-11, EP-01 to EP-04 | Criteria extracted + confirmable in UI; extraction P/R measured on gold set; literature review draft exists |
| **M2** | Links + Evidence v1 (cheap) | LK-01 to LK-08, EV-01 to EV-03, EV-06 to EV-08 | IEG built per PR; tamper rules catch the rule-catalog fixtures; static assertion strength works; link P/R measured |
| **M3** | Verdict v2 (alpha) | VD-01 to VD-08 | Per-criterion states in PR comment; justification tree; policy + waivers; v1 unaffected behind flag |
| **M4** | Mutation + Evidence v2 | EV-04, EV-05, EV-09 to EV-11 | Mutation runs on changed symbols within budget, sandboxed; `q(e)` uses `d_mut`; RQ2 first results |
| **M5** | Process + Calibration | PR-01 to PR-08, CA-01 to CA-08 | Trajectory ingestion works for at least 2 agent sources; calibrated P with reliability curve on held-out data; abstention works |
| **M6** | Triage + Manager + Integrations | TR-*, MG-*, IT-* | Triage list + re-prompt shipped; manager portfolio shipped; MCP/CLI/Action v2 shipped |
| **M7** | Launch + Paper | PL-*, EP-05 to EP-14, QS-* complete | Design partners onboarded; paper draft complete with all RQs; security review done; docs site live |

Suggested order of effort (relative): M0 1x, M1 1x, M2 1.5x, M3 1x, M4 1.5x, M5 2x, M6 2x, M7 1.5x.

---

## 5. Task index

Status tags are updated in the task files; this table is the map.

### Foundations (`tasks/F-foundations.md`)
F-01 Ratify research direction + DEC entries; F-02 Fix README vs code claims; F-03 Repo hygiene; F-04 Branch-flow reconciliation + default branch; F-05 Remove public API key from dashboard; F-06 Live GitHub App validation; F-07 Sandbox proof and hardening; F-08 Symbol-level impact in selection; F-09 Language scope + parser upgrade (Python first, TS second); F-10 Observability baseline; F-11 Flaky-test handling; F-12 Deprecate heuristic score (flagged, kept until calibration); F-13 CI hardening (coverage, audit, secret scan, SBOM); F-14 Golden fixtures corpus; F-15 One-command dev environment; F-16 Remove committed stray test commit effects (revert note).

### Intent (`tasks/IN-intent.md`)
IN-01 Intent domain model; IN-02 Source ingestion (PR body, issues, commits, spec file, agent prompt); IN-03 Deterministic extraction; IN-04 LLM-assisted extraction (guarded); IN-05 Testability rating; IN-06 Intent snapshots and versioning; IN-07 Persistence (migration); IN-08 API; IN-09 Gold annotation set for RQ1; IN-10 Extraction metrics harness; IN-11 Dashboard Intent panel + confirmation; IN-12 Missing-intent handling and author prompts.

### Linking (`tasks/LK-linking.md`)
LK-01 Symbol-level change extraction; LK-02 Criterion-to-symbol linkers; LK-03 Symbol-to-test linkers incl. dynamic coverage contexts; LK-04 Test assertion extraction; LK-05 IEG builder and persistence; LK-06 Link combination and confidence; LK-07 Link evaluation harness (RQ1); LK-08 IEG API and viewer; LK-09 Incremental updates on new commits.

### Evidence quality (`tasks/EV-evidence-quality.md`)
EV-01 Evidence item model and normalizers; EV-02 Tamper rule engine + catalog (Python); EV-03 Authorship/independence analysis; EV-04 Mutation service (Python); EV-05 Detection power `d_mut`; EV-06 Static assertion strength `a_static`; EV-07 Freshness binding and staleness; EV-08 `q(e)` combiner + config; EV-09 Mutation caching and budgets; EV-10 Equivalent/ flaky mutant handling; EV-11 Evidence API and UI; EV-12 (stretch) adversarial probe generation; EV-13 Evidence for non-behavioral intent (refactor/config/docs); EV-14 TypeScript tamper rules + mutation adapter; EV-15 Non-functional evidence (perf/security) hooks.

### Verdict v2 (`tasks/VD-verdict-v2.md`)
VD-01 Support `S(c)` aggregation; VD-02 UIM and per-criterion states; VD-03 Verdict rules v2 + justification tree; VD-04 Policy engine (`.radius.yml`); VD-05 Waivers with expiry/audit; VD-06 PR comment/Check Run v2 + republish after CI; VD-07 Feature flags + v1 compatibility; VD-08 Explainability renderer; VD-09 Required-check / branch-protection guidance.

### Process verification (`tasks/PR-process-verification.md`)
PR-01 Trajectory schema; PR-02 Ingestion API; PR-03 `radius run` wrapper + baseline snapshots; PR-04 Adapters for agent sources; PR-05 Git-history inference when no trace; PR-06 Process signal extractors; PR-07 Lucky-pass indicator; PR-08 Redaction/retention; PR-09 Provenance labeling (agent vs human); PR-10 RQ4 analysis notebook/pipeline.

### Calibration (`tasks/CA-calibration.md`)
CA-01 Outcome label pipeline; CA-02 Feature store; CA-03 Baseline + calibration models; CA-04 Conformal risk control + abstention; CA-05 Metrics and reporting; CA-06 Cold start, online updates, drift; CA-07 Model registry + audit; CA-08 Reliability UI; CA-09 Label quality study.

### Triage (`tasks/TR-triage.md`)
TR-01 Hunk risk model; TR-02 Review budget allocation; TR-03 Triage UI + PR comment section; TR-04 Agent re-prompt generator; TR-05 RQ5 evaluation (replay and user study).

### Manager layer (`tasks/MG-manager.md`)
MG-01 Org/team/agent entity model; MG-02 Metrics definitions; MG-03 Portfolio dashboards; MG-04 Trends + agent comparison; MG-05 Exports + scheduled digests; MG-06 RBAC + audit log; MG-07 Notifications; MG-08 Waiver/approval workflows UI.

### Integrations (`tasks/IT-integrations.md`)
IT-01 GitHub App polish + install flow; IT-02 `radius` CLI; IT-03 GitHub Action v2; IT-04 MCP server for agents (pre-push self-verification); IT-05 Agent hooks (Claude Code etc.); IT-06 Evidence importers (JUnit, SARIF, coverage, TestSprite-style JSON); IT-07 Issue trackers (Plane, Jira, Linear); IT-08 Rule-pack plugin interface; IT-09 Public API docs + scoped keys; IT-10 GitLab/Bitbucket (later).

### Quality, security, ops (`tasks/QS-quality-security-ops.md`)
QS-01 Threat model; QS-02 Prompt-injection test suite; QS-03 Sandbox pen-test; QS-04 Tenant isolation test suite; QS-05 Secrets and dependency scanning; QS-06 Data retention/privacy; QS-07 Load/perf tests; QS-08 SLOs and alerts; QS-09 Replay command + determinism tests; QS-10 Cost controls (LLM, compute); QS-11 Backup/DR; QS-12 Accessibility/UX review; QS-13 Licensing review.

### Product / launch (`tasks/PL-product-launch.md`)
PL-01 Personas and journeys; PL-02 Positioning and messaging; PL-03 Onboarding flow; PL-04 Demo repo + scripted demo; PL-05 Docs site; PL-06 Design-partner program; PL-07 Pricing hypotheses; PL-08 Telemetry (opt-in) and success metrics; PL-09 OSS/community strategy; PL-10 Launch plan; PL-11 Feedback loop into roadmap.

### Evaluation / paper (`EVALUATION_PLAN.md`)
EP-01 Literature review; EP-02 Hypotheses and pre-registration; EP-03 Datasets; EP-04 Gold annotation; EP-05 Experiment harness through production pipeline; EP-06 Baselines; EP-07 RQ1 experiments; EP-08 RQ2; EP-09 RQ3; EP-10 RQ4; EP-11 RQ5; EP-12 Ablations; EP-13 Threats to validity; EP-14 Paper writing + artifact.

---

## 6. Security checklist (apply when relevant)

- [ ] Untrusted text (PR, issue, trace, test output) is never executed, never interpolated into shell/SQL, and is size-limited.
- [ ] LLM prompts treat sources as data; outputs are schema- and span-validated; no tool access.
- [ ] Execution (tests, mutation) only in the sandbox with no network and no secrets.
- [ ] Redaction before storage and before any LLM call.
- [ ] Org isolation tests added.
- [ ] Rate limits and size limits on new endpoints.
- [ ] No new secrets in client bundles (`NEXT_PUBLIC_*`).

---

## 7. Risks to the whole plan (and mitigations)

| Risk | Mitigation |
|---|---|
| Intent extraction is too noisy | Human confirmation loop (IN-11), measure early (IN-09/10), fall back to explicit `.radius/intent.yml`, keep vague criteria visible |
| Mutation testing is slow/expensive | Changed-symbol scope, caching (EV-09), sampling, budgets, async publish |
| No labels for calibration | Benchmark labels first (EP-03), revert/SZZ pipeline (CA-01), explicit "uncalibrated prior" UI |
| Scope too big for the calendar | Milestone gates; M0-M3 already give a demo-able product and a partial paper; M4-M6 are staged |
| Novelty claim fails | Literature review early (EP-01); adjust claim to the proven gap |
| Prompt injection / sandbox escape | QS-02, QS-03; verdict never depends on an LLM |
| Adoption is low | Design partners (PL-06), MCP/Action distribution (IT-03/04), clear demo value in under 5 minutes |

---

## 8. Production-readiness track (PRD-xx)

A researched gap analysis against OSS, supply-chain, security and accessibility standards lives in [../production-readiness/AUDIT.md](../production-readiness/AUDIT.md). Its build-ready backlog (`PRD-01` to `PRD-36`, in waves, with a v1.0 definition-of-done checklist) is [../production-readiness/BACKLOG.md](../production-readiness/BACKLOG.md). The backlog cross-references the QS-, IT-, PL- and MG- tasks it relies on and does not duplicate them; the v1.0 checklist is an additional gate beside M7.
