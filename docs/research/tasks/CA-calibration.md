# Phase CA: Calibrated Trust (Milestone M5) -- RQ3

Goal: make "87% confident" mean that about 87% of such PRs really are correct, and let the system abstain when it cannot say. See `../DESIGN.md` section 6.7. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### CA-01 Outcome label pipeline   [ ]
- Label-source order and partner-data rules: DEC-020 (public benchmark labels first, partner data only with written opt-in).
- Owner type: pair
- Depends on: F-06, VD-07
- Branch: `feature/calibration-labels`
- Size: XL (split by label source)
- Goal: build `outcome_label` rows from real repository history and benchmarks.
- Label sources:
  1. **Benchmark truth**: SWE-bench-style datasets with hidden/augmented tests, and Radius' own mutation benchmark (P3). Labels: correct / plausible-but-incorrect.
  2. **Revert detection**: `git revert` commits, "Revert ..." PRs; link back to the original PR/SHA.
  3. **Follow-up fix (SZZ-style)**: later commits/PRs that fix lines introduced by the PR within a horizon (default 30 and 90 days); filter noise (refactors, formatting, unrelated bugs).
  4. **Incident/issue links**: bug issues referencing the PR/commit (GitHub issue links, labels like `bug`/`regression`).
  5. **Human labels**: reviewer overrides in the dashboard ("this was wrong").
- Steps: label model with `label`, `source`, `confidence`, `observed_at`, `horizon_days`; right-censoring (PRs too recent are `unknown`, not `correct`); migration `0017`; backfill job `backfill_outcomes`.
- Acceptance: label precision measured on a manually checked sample (CA-09); censoring handled and documented; no label leakage into features (time-based split enforced).
- Research hook: this is the dataset construction section of the paper.

### CA-02 Feature store   [ ]
- Owner type: agent-ok
- Depends on: VD-03, PR-06
- Branch: `feature/calibration-features`
- Size: M
- Goal: one row per PR assessment with features: support distribution (min, mean, quantiles), UIM, counts of states, `d_mut` summary, tamper counts by severity, process signals, change size, blast-radius size, language, provenance, intent quality (testability mix), policy mode.
- Acceptance: features reproducible for any historical assessment; versioned feature set; no future information used (tested with time-travel tests).

### CA-03 Baseline and calibration models   [~] isotonic and Platt fitters ready; no model, no data
- Owner type: agent-ok
- Depends on: CA-01, CA-02
- Branch: `feature/calibration-models`
- Size: L
- Goal: logistic regression baseline; isotonic and Platt calibration; optional gradient-boosted model for comparison; strict train/validation/test splits by time and by repository.
- Acceptance: pipeline script trains, calibrates, evaluates; reports ECE, Brier, AUROC, reliability curves with bootstrap CIs; models serializable and versioned (CA-07).
- Research hook: baselines (CI-pass only, coverage, v1 score) trained on the same labels for fair comparison (EP-06).
- Status (2026-11-03): **partial, library only.** Delivered: isotonic (PAV) and Platt fitters, the `Calibrator` hook interface and a minimum-N guard in `packages/confidence/src/radius_confidence/calibration/` (`../evaluation/CALIBRATION_TOOLKIT.md`). Not delivered: the logistic baseline, the feature pipeline, time/repo splits, AUROC, serialization/versioning; nothing is fitted on real labels and nothing is wired into the verdict.

### CA-04 Conformal risk control and abstention   [~] procedures implemented and simulated; open loss question; no real data
- Owner type: pair
- Depends on: CA-03
- Branch: `feature/calibration-conformal`
- Size: L
- Goal: choose accept/defer thresholds so the error rate among accepted PRs is at most alpha (default 0.05) with finite-sample guarantees under exchangeability; produce the `needs_review` decision and intervals.
- Steps: split-conformal procedure on a held-out calibration set; per-segment thresholds (language, size) when enough data; clear statement of assumptions and what breaks under distribution shift; selective accuracy vs coverage curve.
- Acceptance: empirical error among accepted <= alpha (within CI) on held-out data; behavior when calibration set is small is "abstain more", never "accept more".
- Research hook: likely a main novelty claim (conformal risk control applied to PR verification). Confirm novelty in EP-01.
- Status (2026-11-03): **partial, library only.** Delivered: `ltt_threshold` (accepted-set error, exact binomial, Bonferroni grid), `crc_threshold` (joint false-accept rate), risk-coverage curve and a small-N rule that abstains on everything, with seeded simulations of the finite-sample statements on synthetic data. **Open finding:** the shifted loss in PREREGISTRATION 7.1 is not non-increasing in the threshold per item, so the CRC theorem does not apply to it unmodified (`CALIBRATION_TOOLKIT.md`); the owner/implementer must decide the formulation before freeze. Not delivered: per-segment thresholds, the `needs_review` integration, any run on real labels.

### CA-05 Metrics and reporting   [~] metrics and report script ready; no real data
- Owner type: agent-ok
- Depends on: CA-03
- Branch: `feature/calibration-metrics`
- Size: M
- Goal: standard report generator (ECE with fixed bins and adaptive bins, Brier decomposition, reliability diagram data, AUROC/PR-AUC, selective risk-coverage), per segment.
- Acceptance: unit-tested metric functions against known values; report reproducible.
- Status (2026-11-03): **partial.** Delivered: ECE (equal-width and equal-mass), MCE, Brier with decomposition, log loss, reliability-curve data, risk-coverage, bootstrap (optionally clustered) and Clopper-Pearson intervals, unit-tested against hand-computed values; `scripts/calibration_report.py` writes a deterministic markdown + JSON report (synthetic example in `../examples/`). Not delivered: AUROC/PR-AUC, DeLong and paired tests, per-segment reports on real data, the noise-floor recomputation (PREREGISTRATION 7.5).

### CA-06 Cold start, online updates, drift   [ ] (only the N-guard and the "uncalibrated prior" state exist, as library code)
- Owner type: pair
- Depends on: CA-03
- Branch: `feature/calibration-lifecycle`
- Size: M
- Goal: use a benchmark-trained prior with an explicit "uncalibrated prior" label until `n_labels >= N_min` per org/segment; scheduled refits; drift detection on features and calibration error; automatic fall-back to the previous model.
- Acceptance: simulated drift triggers an alert; refit does not silently replace a better model; UI shows the model's training size and date.

### CA-07 Model registry and audit   [ ]
- Owner type: agent-ok
- Depends on: CA-03
- Branch: `feature/calibration-registry`
- Size: M
- Goal: `calibration_model` table (migration `0018`) with metrics, training window, label counts, code version; promote/rollback; every `trust_assessment` references the model id.
- Acceptance: past assessments remain explainable with the model that produced them; promotion requires passing a metrics gate.

### CA-08 Reliability UI   [ ]
- Owner type: agent-ok
- Depends on: CA-05
- Branch: `feature/dashboard-reliability`
- Size: M
- Goal: show the calibrated probability with interval, the reliability diagram for the org/segment, number of labels, and when the model is only a prior. Plain-language caption ("PRs we rated 80-90% were correct 86% of the time (n=212)").
- Acceptance: misleading precision avoided (rounded, intervals shown); accessible charts (follow the dataviz skill guidelines for color/contrast).

### CA-09 Label quality study   [ ]
- Owner type: human-required
- Depends on: CA-01
- Branch: `docs/calibration-label-quality`
- Size: M
- Goal: manually audit a random sample (>= 200 labels) per source; estimate precision/recall of each label source; report.
- Acceptance: documented noise rates used to correct or caveat results (threats to validity).
