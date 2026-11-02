# Phase MG: Manager Layer (Milestone M6)

Goal: give managers and leads a trustworthy, aggregate view of agent-assisted delivery risk, without creating surveillance of individuals. Template and rules: `../IMPLEMENTATION_PLAN.md`.

Principles: aggregate by team/repo/agent tool, not by named individual by default; every number links to evidence; show uncertainty; no vanity metrics.

---

### MG-01 Org, team and agent entity model   [ ]
- Owner type: agent-ok
- Depends on: F-06
- Branch: `feature/org-teams-agents`
- Size: L
- Goal: model organizations, teams (from GitHub teams/CODEOWNERS), repositories, and "agent identities" (tool + model, from provenance and trajectory data). Migration `0019`.
- Acceptance: tenant isolation tests; team membership sync job; PRs attributable to team/agent without exposing individual names unless policy allows.

### MG-02 Metric definitions   [ ]
- Owner type: pair
- Depends on: VD-03, CA-02
- Branch: `docs/manager-metrics`
- Size: M
- Goal: a written spec (formula, data source, caveats) for each metric:
  - Calibrated trust distribution (share of PRs verified / needs_review / insufficient / failed).
  - Unevidenced intent rate; weak-test rate (share of changed symbols with low `d_mut`).
  - Tamper rate by rule family.
  - Agent-authored PR share and trust vs human PRs.
  - Post-merge defect rate (reverts/follow-up fixes) vs predicted risk (calibration check).
  - Time to verified; re-prompt iterations to verified.
  - Estimated review effort saved (explicit assumptions; label as estimate).
  - Policy compliance and waiver counts/age.
- Acceptance: each metric has an owner, a test, and "how this can mislead" note; no metric computed without a documented definition.

### MG-03 Portfolio dashboards   [ ]
- Owner type: agent-ok
- Depends on: MG-01, MG-02
- Branch: `feature/dashboard-portfolio`
- Size: XL
- Goal: org overview (risk heatmap by repo/team), repo drill-down, PR list sorted by risk, links to evidence. Server-side aggregation with caching; pagination; empty states.
- Acceptance: performance target (p95 < 2 s for 10k PRs); numbers match the metric spec (golden tests); accessible visuals.

### MG-04 Trends and agent comparison   [ ]
- Owner type: agent-ok
- Depends on: MG-03
- Branch: `feature/dashboard-trends`
- Size: L
- Goal: time series of trust, tamper rate, weak-test rate; compare agent tools/models with normalization (by change size, language) and with confidence intervals; warn when sample sizes are too small.
- Acceptance: no ranking shown without sufficient n; caveats visible; export of underlying data.
- Product hook: "which agent setup gives us the most verified code?" is a question nobody can answer today.

### MG-05 Exports and scheduled digests   [ ]
- Owner type: agent-ok
- Depends on: MG-03
- Branch: `feature/reports-exports`
- Size: M
- Goal: CSV/JSON export and PDF summary; weekly email/Slack digest with top risks, trend changes, waivers expiring.
- Acceptance: digests respect RBAC; unsubscribe/mute; contents match the dashboard.

### MG-06 RBAC and audit log   [ ]
- Owner type: agent-ok
- Depends on: MG-01
- Branch: `feature/rbac-audit`
- Size: L
- Goal: roles `viewer`, `developer`, `manager`, `admin`, `auditor`; permission matrix; every sensitive action (policy edit, waiver, label override, export) recorded in `audit_log`.
- Acceptance: permission matrix tests (deny by default); audit log immutable from the app; admin cannot silently edit logs.

### MG-07 Notifications   [ ]
- Owner type: agent-ok
- Depends on: MG-06
- Branch: `feature/notifications`
- Size: M
- Goal: notify on `failed`/`needs_review` for protected paths, expiring waivers, calibration drift, and failed jobs; channels: email, Slack/Teams webhook; per-user preferences.
- Acceptance: no duplicate notifications for the same event; rate-limited.

### MG-08 Waiver and approval workflows UI   [ ]
- Owner type: agent-ok
- Depends on: VD-05, MG-06
- Branch: `feature/dashboard-waivers`
- Size: M
- Goal: request, approve, expire waivers; show who/why/when; list of active waivers per repo.
- Acceptance: workflow tests for each role; waiver reflected in PR comment.
