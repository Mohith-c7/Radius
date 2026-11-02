# Phase QS: Quality, Security and Operations (continuous across all milestones)

Goal: a verification product must itself be trustworthy. Template and rules: `../IMPLEMENTATION_PLAN.md`. Tasks here are scheduled alongside the feature they protect (see "When").

---

### QS-01 Threat model   [ ]
- Owner type: pair
- When: before M2; update each milestone
- Depends on: F-01
- Branch: `docs/threat-model`
- Size: M
- Goal: STRIDE-style model of the whole system: assets (customer code, tokens, traces), actors (malicious PR author, malicious agent, curious tenant, compromised dependency), entry points (webhooks, uploads, LLM inputs, MCP tools), trust boundaries (API, worker, sandbox, LLM provider).
- Acceptance: documented risks with mitigations mapped to tasks; reviewed by a second person.

### QS-02 Prompt-injection test suite   [x]
- Owner type: agent-ok
- When: with IN-04 (harness and corpus pulled forward so IN-04 can register against them; IN-04 adds its adapter in `tests/security/prompt_injection/pi_registry.py`)
- Depends on: IN-04
- Docs: `docs/security/PROMPT_INJECTION.md`; code: `packages/shared/src/radius_shared/llm_guard/`; suite: `tests/security/prompt_injection/` (corpus v1, 98 cases). Regression rule stays open: every future bypass adds a corpus case.
- Branch: `feature/security-prompt-injection`
- Size: M
- Goal: corpus of adversarial PR bodies/issues/commit messages/trajectories ("ignore instructions", fake system messages, hidden unicode, markdown tricks, oversized inputs, instructions to mark a PR verified) run against every LLM-using component.
- Acceptance: LLM outputs never change verdict logic; schema/span validation rejects malicious outputs; results tracked in CI; regression added for every discovered bypass.

### QS-03 Sandbox penetration test   [ ]
- Owner type: human-required
- When: before M4
- Depends on: F-07, EV-04
- Branch: `docs/sandbox-pentest`
- Size: M
- Goal: independent attempt to escape or abuse the execution sandbox (network, filesystem, resource exhaustion, side channels, symlinks, `/proc`, container runtime misconfig).
- Acceptance: findings fixed or documented as accepted risk; mutation testing remains disabled by default for untrusted repos until passed.

### QS-04 Tenant isolation test suite   [ ]
- Owner type: agent-ok
- When: continuous
- Depends on: none
- Branch: `feature/security-tenant-isolation`
- Size: M
- Goal: automated tests that, for every endpoint and table, prove tenant A cannot read or write tenant B (including via IDs, search, exports, caches, queue, logs).
- Acceptance: test generated from the route table so new endpoints without isolation tests fail CI.

### QS-05 Secrets and dependency scanning   [ ]
- Owner type: agent-ok
- When: M0
- Depends on: F-13
- Branch: `ci/security-scanning`
- Size: S
- Goal: gitleaks (incl. history), dependency audit, container image scan (Trivy), license scan, SBOM, Dependabot/Renovate.
- Acceptance: fails CI on high severity; baseline file for accepted risks with expiry.

### QS-06 Data retention and privacy   [ ]
- Owner type: human-required (policy) + agent-ok (implementation)
- When: before M5
- Depends on: QS-01
- Branch: `feature/privacy-retention`
- Size: L
- Goal: define what is stored (diffs, source snippets, traces, LLM inputs), for how long, how it is deleted on uninstall/request, what leaves the customer boundary (LLM calls), and what telemetry is collected (opt-in).
- Acceptance: retention jobs with tests; data map document; deletion verified end to end; DPA/privacy-policy inputs prepared; policy switch "no code egress" disables cloud LLM features.

### QS-07 Load and performance tests   [ ]
- Owner type: agent-ok
- When: before M6
- Depends on: VD-06
- Branch: `feature/perf-tests`
- Size: M
- Goal: synthetic repos of increasing size; measure end-to-end latency per stage (parse, graph, link, tamper, mutation, publish), queue throughput, DB query plans.
- Acceptance: documented budgets (e.g. cheap verdict < 2 min; mutation async); regressions fail a nightly job.
- Research hook: overhead table in the paper.

### QS-08 SLOs and alerting   [ ]
- Owner type: pair
- When: before M7
- Depends on: F-10
- Branch: `feature/ops-slo`
- Size: M
- Goal: SLOs (webhook-to-first-comment latency, job success rate, publish success rate), dashboards, alerts, runbooks.
- Acceptance: runbook for each alert; game-day exercise performed once.

### QS-09 Replay command and determinism tests   [ ]
- Owner type: agent-ok
- When: with VD-03
- Depends on: VD-03
- Branch: `feature/replay`
- Size: M
- Goal: `radius replay <assessment-id>` recomputes an assessment from stored inputs and config and compares outputs byte for byte (excluding timestamps).
- Acceptance: nightly job replays a sample of assessments and alerts on any difference; LLM steps replay from cache.
- Research hook: reproducibility claim for the paper's artifact.

### QS-10 Cost controls   [ ]
- Owner type: agent-ok
- When: with IN-04 and EV-04
- Depends on: F-10
- Branch: `feature/cost-controls`
- Size: M
- Goal: per-org budgets for LLM tokens and sandbox CPU-minutes; graceful degradation (skip LLM/mutation, mark `partial`); cost shown in the admin UI.
- Acceptance: tests simulate budget exhaustion; no verdict is published as complete when a required stage was skipped.

### QS-11 Backup and disaster recovery   [ ]
- Owner type: human-required
- When: before M7
- Depends on: none
- Branch: `docs/dr-plan`
- Size: S
- Goal: documented backup schedule, restore test, RPO/RTO targets, migration rollback procedure.

### QS-12 Accessibility and UX review   [ ]
- Owner type: pair
- When: each UI milestone
- Depends on: UI tasks
- Branch: `fix/a11y-*`
- Size: M
- Goal: keyboard navigation, screen reader labels, contrast in light/dark, no color-only meaning (important for state badges), reduced-motion, readable on narrow screens.
- Acceptance: automated checks (axe) in CI plus a manual pass.

### QS-13 Licensing review   [ ]
- Owner type: human-required
- When: before M6 and before any open-sourcing
- Depends on: F-01
- Branch: `docs/licensing`
- Size: S
- Goal: confirm licenses of all dependencies and of any code or rules borrowed or adapted (Verik is Apache-2.0; AgentProof and SlopGate licenses to be confirmed), choose Radius' own license (DESIGN 11.4), add NOTICE/attribution files.
- Acceptance: legal sign-off checklist complete; no unlicensed code in the repo.
