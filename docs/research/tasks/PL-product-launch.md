# Phase PL: Product, Market and Launch (continuous; heavy in M6-M7)

Goal: make Radius something people adopt, understand in minutes, and pay for. Companion: `../PRODUCT_AND_GTM.md`. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### PL-01 Personas and journeys   [ ]
- Owner type: human-required
- Depends on: none
- Branch: `docs/product-personas`
- Size: M
- Goal: written personas (agent-heavy developer, tech lead/reviewer, engineering manager, security/compliance lead, OSS maintainer) with their jobs, pains, current workaround and the "aha moment" in Radius; end-to-end journeys (install -> first PR -> first red finding -> fix -> verified -> weekly report).
- Acceptance: >= 8 customer interviews (see PL-06) feed the personas; journeys have measurable steps.

### PL-02 Positioning and messaging   [ ]
- Owner type: human-required
- Depends on: PL-01
- Branch: `docs/product-positioning`
- Size: M
- Goal: one-sentence positioning, the category claim ("evidence-based merge confidence for agent-written code"), 3 proof points, competitor contrast (see GTM doc), and words to avoid (never claim guarantees).
- Acceptance: tested messaging in 5+ conversations; README and website copy follow it.

### PL-03 Onboarding flow   [ ]
- Owner type: pair
- Depends on: IT-01, IN-11
- Branch: `feature/dashboard-onboarding`
- Size: L
- Goal: from sign-in to first verdict in under 10 minutes: install the App, pick a repo, see the first PR analysed (or a sample PR), prompt to add acceptance criteria, show the first criteria matrix and a surviving-mutant example.
- Acceptance: time-to-first-value measured (opt-in telemetry); empty states instructive; usability test with 5 people.

### PL-04 Demo repository and scripted demo   [ ]
- Owner type: pair
- Depends on: M3 minimum (VD-06), better after M4
- Branch: `docs/demo`
- Size: M
- Goal: a public demo repo with 4 scripted PRs: (1) good agent PR, verified; (2) agent PR whose tests pass but are weak, flagged with a surviving mutant; (3) agent PR that weakens tests, flagged by tamper rules; (4) large agent PR where triage shows the 10 hunks to review. A 3-minute video and a live script.
- Acceptance: reproducible from a script; demo works offline-ish (cached LLM results).

### PL-05 Documentation site   [ ]
- Owner type: agent-ok
- Depends on: IT-09
- Branch: `docs/site`
- Size: L
- Goal: docs site: quickstart, concepts (criteria, evidence quality, support, calibration), policies, FAQ ("what Radius does not guarantee"), API reference, security and privacy page, changelog, research page linking the paper and datasets.
- Acceptance: quickstart tested by someone new; docs build in CI; links checked.

### PL-06 Design-partner program   [ ]
- Owner type: human-required
- Depends on: M3
- Branch: n/a
- Size: L
- Goal: recruit 5-10 teams that use coding agents heavily (startups, student teams, OSS maintainers) for free early access in exchange for feedback and (anonymized, consented) data for calibration and evaluation.
- Steps: outreach list; one-page pitch; data-sharing agreement; weekly feedback calls; issue-tracking of feedback; success criteria per partner.
- Acceptance: signed data terms; >= 3 active partners by M5; findings summarized in `docs/research/partners.md` (no confidential data).
- Research hook: real-world labels and the user study pool (TR-05).

### PL-07 Pricing hypotheses   [ ]
- Owner type: human-required
- Depends on: PL-06
- Branch: `docs/pricing`
- Size: S
- Goal: documented hypotheses to test (e.g. free for OSS and small teams; per active contributor or per verified PR volume; managed sandbox compute as a metered add-on; self-hosted enterprise tier with SSO/audit). Avoid unpredictable credit pricing (a complaint about competitors).
- Acceptance: tested with partners; predictable bills.

### PL-08 Product telemetry (opt-in) and success metrics   [ ]
- Decision 2026-11-02: DEC-023 (opt-in, anonymous, no code or intent text, no phone-home by default) is binding for this task.
- Owner type: agent-ok
- Depends on: QS-06
- Branch: `feature/telemetry-optin`
- Size: M
- Goal: privacy-respecting usage analytics (events, no code) to measure activation, retention, and value: time to first verdict, criteria confirmed, findings acted on (commit after finding), re-prompt adoption, false-positive reports.
- North-star metric (hypothesis): "verified-by-evidence PRs per week" and "agent-PR defects caught before merge".
- Acceptance: opt-in; documented events; no PII or code content.

### PL-09 Open-source and community strategy   [~]
- Status 2026-11-02: license decided by delegation (DEC-018, Apache-2.0 open core; `LICENSE`, `NOTICE`, `CONTRIBUTING.md` with DCO added, DEC-022). Still open: code of conduct, roadmap transparency, benchmark leaderboard, labelled first issues, owner acceptance of DEC-018 before any public release.
- Owner type: human-required
- Depends on: QS-13
- Branch: `docs/oss-strategy`
- Size: M
- Goal: decide what is open (core engine, rule packs, benchmark, schemas) vs hosted/paid (managed sandbox, calibration data network effects, dashboards, SSO); contribution guide; code of conduct; roadmap transparency; benchmark leaderboard.
- Acceptance: license chosen; CONTRIBUTING.md present; first external-contributor-friendly issues labelled.

### PL-10 Launch plan   [ ]
- Owner type: human-required
- Depends on: M6
- Branch: n/a
- Size: M
- Goal: sequenced launch: private beta -> paper preprint + benchmark release -> public beta (GitHub Marketplace listing) -> community posts and demos; support channel; status page.
- Acceptance: checklist complete; rollback plan for bad launch.

### PL-11 Feedback loop into the roadmap   [ ]
- Owner type: human-required
- Depends on: PL-06
- Branch: n/a
- Size: S
- Goal: fixed cadence (every two weeks) to triage feedback, update this plan, and record changes in `docs/research/CHANGELOG.md`.
