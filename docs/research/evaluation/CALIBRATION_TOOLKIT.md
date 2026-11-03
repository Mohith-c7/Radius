# Calibration toolkit and report script (CA-03/04/05 groundwork)

Status: **tooling only. No calibration has been done, measured or claimed.** Verdict v2 is still `heuristic_uncalibrated` / `calibrated: false`; nothing in the verdict path imports this code (an import-linter contract enforces it, `packages/confidence/.importlinter`). Everything produced by the tests and by the committed example is synthetic or hand-computed and is not a research result.

What it is for: when real outcome labels exist (CA-01, `L_ABS`, a second annotator's gold), the metrics, intervals, guards and abstention rules below are ready and tested, so the first real calibration number goes through a reviewed code path instead of a notebook.

## Where things are

| Piece | Path |
|---|---|
| Library (stdlib only) | `packages/confidence/src/radius_confidence/calibration/` |
| Tests | `packages/confidence/tests/test_calibration_*.py` |
| Report CLI | `scripts/calibration_report.py` (test: `tests/test_calibration_report.py`) |
| Synthetic example (labelled) | `docs/research/examples/calibration_report_SYNTHETIC.{md,json}` and its input `calibration_input_SYNTHETIC.jsonl` |
| Import contract | `packages/confidence/.importlinter` (CI step "calibration toolkit purity") |

## Contents of the library

* `metrics`: reliability bins (equal-width, equal-mass), ECE, MCE, Brier score and its binned decomposition, log loss, reliability-curve data, and `ece_noise_floor` (the ECE a perfectly calibrated predictor still shows at a given N and score distribution; the 7.5 recomputation step, run on supplied scores).
* `calibrators`: `IsotonicCalibrator` (pool-adjacent-violators, ties pooled), `PlattCalibrator` (Newton, Platt target smoothing), `UncalibratedPrior` (identity, labelled).
* `intervals`: Clopper-Pearson (exact), seeded percentile bootstrap with optional cluster resampling.
* `risk_control`: risk-coverage curve, `ltt_threshold`, `crc_threshold`, `evaluate_threshold`, and `find_nonincreasing_violation` (see the finding below).
* `guards`: `CalibrationPolicy` (declared minimum N values, **no defaults**), `evaluate_calibration`, `fit_calibrator`, `select_threshold`.
* `protocol`: the `Calibrator` hook interface and `CalibrationState` (`uncalibrated_prior`, `fitted`).

## The guard

Below the declared N (or with a class count below its minimum) the report contains **no calibration number**: `state = uncalibrated_prior`, `metrics = null`, and the reasons. `fit_calibrator` then returns the identity `UncalibratedPrior`, and `select_threshold` returns a decision that abstains on everything. The direction is always "abstain more, never accept more". Above the minimum the state is `estimate_reported`, which means only "N is at least the declared minimum"; it is never a statement that the model is calibrated. The minimum N values are analysis choices that belong in the pre-registration; the draft mentions N_test >= 2,000 for H3a and isotonic only from 1,000 calibration items (initial guesses, not frozen), and the code hard-codes neither.

## Abstention procedures and what each one guarantees

Two procedures, because they bound different quantities (conventions: `correct = 1` means accepting would be right).

1. `ltt_threshold`, Learn-then-Test style. Fixed grid of thresholds chosen before seeing labels; exact one-sided Clopper-Pearson test of "error among accepted > alpha" at level `delta / len(grid)` (Bonferroni); the lowest certified threshold is chosen. Statement: with probability at least `1 - delta` over the calibration draw, `P(incorrect | confidence >= t) <= alpha` for the selected `t`. Needs i.i.d. calibration and deployment data, correct labels, and says nothing about any single PR. Conservative by construction (Bonferroni over the grid and exact binomial bounds), so with modest N it often certifies nothing.
2. `crc_threshold`, conformal risk control (`Angelopoulos2024crc`) with loss `1[incorrect and accepted]`. Statement: under exchangeability the expected **joint** rate `P(accepted and incorrect) <= alpha`. The accepted-set error equals that joint rate divided by coverage and can exceed alpha, so this is not the quantity PREREGISTRATION 7.1 calls "error among accepted".

If nothing can be certified, or N is below the guard, both abstain on everything.

### Finding for the owner and the CA-05 implementer (not resolved here)

PREREGISTRATION 7.1 says the implementer must verify that the shifted loss `(1[incorrect] - alpha) * 1[accepted at t]` meets the CRC conditions. CRC requires each item's loss to be **non-increasing** in the threshold. For a correct item the shifted loss is `-alpha` while it is accepted and `0` once the threshold passes its confidence, i.e. it **increases**. `find_nonincreasing_violation` returns a concrete counterexample, and `test_prereg_shifted_loss_is_not_nonincreasing_in_the_threshold` pins it with a three-item example. So the theorem as cited does not apply to that loss unmodified. Options (a decision, not made here): bound the joint rate with the monotone loss above and state the weaker claim; keep the accepted-set claim and use the LTT procedure (`delta` is already in the draft as the fallback); or find a CRC formulation for the conditional risk and prove its conditions. Until then, "conformal risk control gives error among accepted <= alpha" must not be written in any result.

## Assumptions and limits

* Exchangeability/i.i.d. is doubtful across repos, agents and time (PREREGISTRATION 7.3); under shift none of the statements above hold, which is why the time-split and leave-one-repo-out results are the primary evidence, not the repartition result.
* Percentile bootstrap intervals are approximate and ECE is biased upward at small N; compare with the noise floor of a perfectly calibrated model at the same N (the draft computed one for an assumed Beta score distribution; recompute it with the real dev scores before freeze).
* Equal-mass binning splits tied scores across bins (documented in `reliability_bins`).
* Isotonic output can be exactly 0 or 1; log loss clips at 1e-15, so one confident mistake dominates it.
* Label noise is not modelled (`L_audit`, CA-09).
* Tests are hand-computed cases (ECE, Brier, log loss, PAV, Clopper-Pearson against direct binomial sums) and seeded simulations of the finite-sample statements on synthetic data. They show the code does what it says on those cases; they do not show that Radius's score is calibrated or that any threshold is good.
