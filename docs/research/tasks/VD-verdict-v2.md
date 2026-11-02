# Phase VD: Verdict v2 and Policy (Milestone M3)

Goal: compute and publish a deterministic, explainable, per-criterion verdict. See `../DESIGN.md` sections 6.4 and 6.5. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### VD-01 Support `S(c)` aggregation   [x]
- Owner type: agent-ok
- Depends on: EV-08, LK-06
- Branch: `feature/verdict-support`
- Size: M
- Goal: `S(c) = 1 - PROD(1 - lambda_kind * q(e,c) * l(c,e))`.
- Steps: per-kind weights `lambda_kind` (config); combined link confidence `l(c,e)` through criterion -> symbol -> test -> evidence; cap number of correlated evidence items (diminishing returns for evidence that exercises identical lines).
- Acceptance: hand-computed golden cases; properties: S in [0,1], monotone in q and l, S=0 with no evidence; deterministic.
- Research hook: store all intermediate values for ablations.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: S(c) formula and caps in 3.9)

### VD-02 UIM and per-criterion states   [x]
- Owner type: agent-ok
- Depends on: VD-01, IN-05
- Branch: `feature/verdict-criterion-states`
- Size: M
- Goal: states `proven | weak | unevidenced | contradicted | excluded` and UIM per `DESIGN.md` 6.4.
- Steps: thresholds in config; `contradicted` triggered by failed independent evidence; `excluded` for vague (per policy) or waived (VD-05) with visible reason.
- Acceptance: state transition table tested; UIM computed with weights; fixtures reproduce expected states.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: states, flags, UIM and intent coverage in 3.9; criterion_support table is Beta (migration 0018))

### VD-03 Verdict rules v2 and justification tree   [x]
- Owner type: agent-ok
- Depends on: VD-02, EV-02
- Branch: `feature/verdict-rules-v2`
- Size: L
- Goal: implement the ordered rules in `DESIGN.md` 6.5; output decision + machine-readable justification tree (rule fired, criteria, evidence ids, thresholds, algo_version). Store in `trust_assessment` (migration `0015`).
- Steps: `needs_review` state defined but only reachable once calibration/abstention exist (CA-04); until then it is produced only by policy triggers (e.g. high-severity process signal) and is feature-flagged.
- Acceptance: every verdict reproduces from stored inputs (`radius replay`, QS-09); justification references only existing ids; rules ordering tested.
- Decision needed (DESIGN 11.2): confirm the fourth state.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: rules R1 to R4 and justification schema in 3.9; verdict_v2 table is migration 0013, not 0015)

### VD-04 Policy engine (`.radius/policy.yml`)   [x] (repository-level file read from the base branch; org defaults, a JSON schema file, `audit_log` rows, mutation-score and typed-evidence settings are not built: see `docs/policy.md`)
- Owner type: agent-ok
- Depends on: VD-03
- Branch: `feature/policy-engine`
- Size: L
- Goal: per-repo/org rules, with org defaults and repo overrides, validated against a JSON schema.
- Config examples: thresholds (`tau_support`, `uim_max`), required criteria sources, behavior of vague criteria, minimum mutation score on changed symbols, tamper rule severities, path-based strictness (e.g. `src/payments/**` stricter), agent-authored PR stricter than human, mutation required or optional, blocking vs advisory mode, required evidence kinds for `non_functional` criteria.
- Acceptance: invalid policy rejected with helpful errors; policy changes recorded in `audit_log`; effective policy visible in UI; policy evaluated deterministically and stored with each assessment.
- Tests: schema tests; precedence tests; path-glob tests.

### VD-05 Waivers with expiry and audit   [x] (file-based on the base branch with owner, reason, 90-day expiry and a per-verdict audit record; no in-product role check: review of `.radius/` is the control)
- Owner type: agent-ok
- Depends on: VD-04, MG-06
- Branch: `feature/policy-waivers`
- Size: M
- Goal: a human with the right role can waive a criterion or rule with a reason and expiry; waivers appear in the PR comment and in reports; expired waivers stop applying.
- Acceptance: waiver requires role + reason; expiry enforced; audit log entries; cannot waive `contradicted` evidence without a higher role (policy).

### VD-06 PR comment and Check Run v2, republish after CI   [x] (renderer and in-place upsert plan; worker publish wiring is VS-08)
- Owner type: agent-ok
- Depends on: VD-03, IN-12
- Branch: `feature/github-publish-v2`
- Size: L
- Goal: publish the per-criterion matrix, top findings, and next actions; update the same comment/check in place (no spam); republish when late CI evidence arrives (audit gap).
- Steps: Markdown templates with collapsible sections; annotations on tamper findings and surviving mutants (Check Run annotations); concise summary line; link to dashboard; rate-limit handling and retries; honest "pending" states (mutation running).
- Acceptance: one comment per PR, updated in place; works for forks (permission limits documented); republish within seconds after CI upload; snapshot tests of rendered Markdown.
- Product hook: the main daily surface for developers.
- Alpha hardening [x] (DEC-030): honest wording (SUPPORTED, disclaimer, caveat in the Check Run title), advisory Check Run conclusions (`RADIUS_VERDICT_V2_CHECK_CONCLUSIONS`), provenance tags and the author-hint cap (`docs/security/VERDICT_V2_THREAT_MODEL.md`).
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: renderer and republish-after-CI in sections 5.5 and 6)

### VD-07 Feature flags and v1 compatibility   [~] (alpha lite done: `RADIUS_FEATURE_VERDICT_V2` off|shadow|on, v1 unchanged when off, shadow stores v2; per-org override and the v1-vs-v2 comparison report are not built)
- Owner type: agent-ok
- Depends on: none (can start early)
- Branch: `feature/flags-v2`
- Size: S
- Goal: flag mechanism (`RADIUS_FEATURE_*`, per-org override) so v2 runs in shadow mode (computed, stored, not published) before replacing v1.
- Acceptance: v1 output unchanged when flags off; shadow mode stores v2 results; comparison report v1 vs v2 on the same PRs.
- Research hook: shadow-mode data is free evaluation data.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: alpha flag RADIUS_FEATURE_VERDICT_V2 = off|shadow|on in 1.3 (task VD-07-lite))

### VD-08 Explainability renderer   [~] (template-based per-criterion text and Why line done; justification-node mapping for every sentence and i18n strings remain)
- Owner type: agent-ok
- Depends on: VD-03
- Branch: `feature/verdict-explain`
- Size: M
- Goal: turn the justification tree into short, accurate, template-based text ("C2 is weak: its only linked test would not fail if line 42 changed; 3 of 4 mutants survived"). Optional LLM polishing must preserve evidence ids and is off by default.
- Acceptance: every sentence maps to a justification node; no unsupported claims; i18n-ready strings.

### VD-09 Required-check and branch-protection guidance   [ ]
- Owner type: agent-ok
- Depends on: VD-06
- Branch: `docs/required-check`
- Size: S
- Goal: docs and scripts for making Radius a required status check; describe advisory vs blocking rollout (start advisory, move to blocking after N weeks of calibrated results).
- Acceptance: tested on a sandbox repo; documented in `docs/CI_INTEGRATION_GUIDE.md`.
