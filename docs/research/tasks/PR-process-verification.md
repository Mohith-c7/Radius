# Phase PR: Process Verification (Milestone M5) -- RQ4

Goal: verify not only the output but *how* the change was produced, to catch "lucky passes". See `../DESIGN.md` section 6.6. Template and rules: `../IMPLEMENTATION_PLAN.md`.

Context: AgentLens (Sahoo et al., arXiv 2605.12925, `Sahoo2026` in `../literature/references.bib`) reports "Lucky Passes", passing runs reached through weak processes. EP-01 verified the number; cite it only with these qualifiers:
- 10.7% of passing trajectories are Lucky Passes, measured on a 1,815-trajectory subset covering 47 tasks (from 2,614 OpenHands trajectories on 60 SWE-bench Verified tasks).
- OpenHands only; the rate ranges from 0.5% to 23.2% across the 8 backends, so it is not a single universal rate.
- Code and data were not released as of arXiv v4 (2026-10-05); do not plan on reusing them.
- It evaluates runs that already pass and needs other passing runs of the same task as the reference, so it cannot be applied to a single new PR. Radius PR-time signals (PR-06, PR-07) have no such reference and are a different, predictive use (RQ4, pre-registered in `../preregistration/PREREGISTRATION.md`).

---

### PR-01 Trajectory schema   [ ]
- Owner type: pair
- Depends on: F-01
- Branch: `feature/trajectory-schema`
- Size: M
- Goal: a versioned, tool-agnostic schema for process traces.
- Fields: agent name/version, model, tool/harness, task/prompt reference (hash), start/end, ordered events: `prompt`, `edit` (file, diff hash), `test_run` (command, result summary), `command` (redacted), `revert`, `retry`, `note`; plus `redaction_level` and `source_format`. Provide JSON Schema + examples. Add a minimal OpenTelemetry-compatible mapping.
- Acceptance: schema validated in tests; examples for two real tools; documented extension rules.

### PR-02 Trajectory ingestion API and storage   [ ]
- Owner type: agent-ok
- Depends on: PR-01
- Branch: `feature/trajectory-ingest`
- Size: M
- Goal: `POST /analyses/{id}/trajectories` (also by repo + head SHA before the analysis exists), `GET`; size limits; schema validation; binding to PR/SHA; tables `trajectory`, `trajectory_event` (migration `0016`).
- Acceptance: malformed or oversized uploads rejected; idempotent uploads; tenant isolation tests; retention setting honored (PR-08).

### PR-03 `radius run` wrapper with baseline snapshots   [ ]
- Owner type: pair
- Depends on: PR-01, IT-02
- Branch: `feature/cli-run-wrapper`
- Size: L
- Goal: `radius run -- <agent command>` snapshots the working tree before and after (git tree objects via a scratch index, never staging or stashing the user's work), separates the agent's edits from human uncommitted work, records events, and submits a trajectory.
- Acceptance: user's pre-existing changes are not attributed to the agent; works on Windows and Linux; does not modify the repo state; failure of Radius never blocks the agent (fail-open) unless `--strict`.
- Note: Verik (Apache-2.0) implements a similar snapshot approach; study it, implement independently, check license terms before reusing code.

### PR-04 Adapters for agent sources   [ ]
- Owner type: agent-ok
- Depends on: PR-01
- Branch: `feature/trajectory-adapters`
- Size: L
- Goal: convert native logs/hooks into the schema for at least two sources (e.g. Claude Code hooks/transcripts, a generic JSONL/OTel adapter); document how to add more.
- Acceptance: fixtures per adapter; unknown fields preserved but not trusted; redaction applied.

### PR-05 Git-history inference when no trace exists   [ ]
- Owner type: agent-ok
- Depends on: LK-01
- Branch: `feature/trajectory-git-inference`
- Size: M
- Goal: infer a coarse process from commit history (commit order, test file edits relative to source edits, force-push count, revert commits, message patterns, bot authorship, co-author trailers).
- Acceptance: signals flagged `inferred` (lower confidence) and never presented as observed; documented limits.

### PR-06 Process signal extractors   [ ]
- Owner type: agent-ok
- Depends on: PR-02 or PR-05
- Branch: `feature/process-signals`
- Size: L
- Goal: implement the signals in `DESIGN.md` 6.6: `test_edit_before_pass`, `assertion_removed_then_green`, `retry_count`, `edit_revert_thrash`, `scope_growth`, `time_to_green`, `late_test_weakening`, `flaky_pass_reliance`, `ignored_failure`, `dependency_added_unverified`.
- Steps: each signal = pure function over events with documented definition, units, and evidence refs; stored in `process_signal` with `algo_version`.
- Acceptance: fixture traces trigger exactly the expected signals; no signal fires on a clean trace; performance on 10k-event traces.
- Research hook: signal distributions agent vs human; predictive analysis (PR-10).

### PR-07 Lucky-pass indicator   [ ]
- Owner type: pair
- Depends on: PR-06, CA-02
- Branch: `feature/process-lucky-pass`
- Size: M
- Goal: combine signals into a single indicator; start rule-based, replace by a learned model only if RQ4 shows benefit. Must be explainable.
- Literature note: the indicator is Radius's own PR-time construct and is not AgentLens's "Lucky Pass" tier. AgentLens defines Lucky on runs that already pass (10.7% of 1,815 trajectories / 47 tasks, OpenHands only, 0.5% to 23.2% across backends, code not released as of v4) using other passing runs of the same task as reference. Do not reuse its percentages as expected Radius rates; if its code is released, re-implement the tiers as a baseline (EP-10).
- Acceptance: documented formula; never used alone to fail a PR; shown as "process risk" with the contributing signals.

### PR-08 Redaction and retention   [ ]
- Owner type: agent-ok
- Depends on: PR-02, QS-06
- Branch: `feature/trajectory-redaction`
- Size: M
- Goal: secret/PII redaction on ingest (regex + entropy + known token formats), configurable retention (default short), per-org opt-out of storing prompts, hashing instead of storing raw text where possible.
- Acceptance: seeded secrets never appear in the DB, logs or API responses (tests); retention job deletes on schedule.

### PR-09 Provenance labeling   [ ]
- Owner type: agent-ok
- Depends on: EV-03, PR-05
- Branch: `feature/provenance-label`
- Size: S
- Goal: label each PR `agent`, `human`, `mixed`, `unknown` with a confidence and the evidence (bot accounts, trailers, trace presence, heuristics); show it in UI/comment; policy can be stricter for agent PRs.
- Acceptance: measured accuracy on a labelled sample; label is advisory, never accusatory in wording.

### PR-10 RQ4 analysis pipeline   [ ]
- Owner type: agent-ok
- Depends on: PR-06, CA-01
- Branch: `feature/bench-process-rq4`
- Size: M
- Goal: reproducible analysis: do process signals add predictive power over outcome-only features (AUROC delta, calibration change, ablations)?
- Acceptance: notebook/script producing tables + plots with CIs; seeds fixed; results stored.
