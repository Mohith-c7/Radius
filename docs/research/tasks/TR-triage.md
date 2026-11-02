# Phase TR: Review Triage (Milestone M6) -- RQ5

Goal: tell humans where to look, so huge agent PRs become reviewable. See `../DESIGN.md` section 6.8. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### TR-01 Hunk risk model   [ ]
- Owner type: pair
- Depends on: VD-02, LK-05
- Branch: `feature/triage-risk-model`
- Size: L
- Goal: compute `risk(h) = base(h) * (1 + beta * u(h))` for every diff hunk.
- `base(h)` features: symbol criticality (fan-in, public API, security-sensitive paths via policy), blast-radius reach, churn history, ownership (CODEOWNERS), size/complexity, tamper hits, and novelty (new vs modified code).
- `u(h)`: unevidenced intent mass attributable to the hunk via the IEG (criteria linked to the hunk's symbols with low support).
- Acceptance: deterministic; each risk has a breakdown; weights configurable; fixture tests with expected rankings.
- Research hook: ablation of each component (EP-12).

### TR-02 Review budget allocation   [ ]
- Owner type: agent-ok
- Depends on: TR-01
- Branch: `feature/triage-budget`
- Size: M
- Goal: given a review budget (lines, minutes, or number of hunks), choose the subset that maximizes covered risk; produce an ordered list; explain what is *not* covered.
- Steps: greedy risk-per-cost selection; show cumulative risk coverage curve; configurable cost model (lines + complexity).
- Acceptance: property tests (greedy never worse than random on fixtures; coverage curve monotone); budget respected exactly.

### TR-03 Triage UI and PR comment section   [ ]
- Owner type: agent-ok
- Depends on: TR-02, VD-06
- Branch: `feature/triage-ui`
- Size: L
- Goal: "Review these first" list in the PR comment (top N hunks with reasons) and a dashboard view with file ordering, risk heat strip, and a "reviewed" checklist stored per user.
- Acceptance: links jump to the right diff lines; reasons are specific ("unevidenced: C2; surviving mutant at line 42").
- Product hook: turns a 4,000-line agent PR into a 10-minute review.

### TR-04 Agent re-prompt generator   [ ]
- Owner type: agent-ok
- Depends on: VD-03, TR-01
- Branch: `feature/triage-reprompt`
- Size: M
- Goal: produce a short, structured re-prompt for the coding agent listing: unmet/unevidenced criteria, surviving mutants (with locations), tamper findings to revert, and out-of-scope edits; each item cites evidence ids. Available via API, CLI (`radius reprompt`), MCP (IT-04) and PR comment.
- Acceptance: deterministic template-based output; no hallucinated items (every line maps to a stored finding); tested for length limits.
- Note: AgentProof also generates re-prompts; ours is evidence-id-grounded and mutation-aware.
- Product hook: closes the loop: verify -> instruct the agent -> re-verify.

### TR-05 RQ5 evaluation (replay and user study)   [ ]
- Owner type: human-required
- Depends on: TR-03, EP-03
- Branch: `docs/triage-evaluation`
- Size: L
- Goal: (a) offline replay: on historical PRs with known defects, how much of the defect lines/hunks fall within the top-k% risk-ranked hunks; (b) a small user study (>= 12 participants, within-subject): find seeded defects with and without triage, measuring time and detection rate.
- Acceptance: pre-registered protocol (EP-02); ethics/consent handled per institution rules; analysis with appropriate statistics (paired tests, effect sizes).
