# Calibration report

> **SYNTHETIC DATA. Not a research result.** The input was generated to exercise this tool.

> **Not a research result.** This report describes only the file supplied, using the tool `calibration-report-v1`. It makes no claim that any model or product score is calibrated. The state `estimate_reported` means only that N reached the declared minimum; `uncalibrated_prior` means the data are too few and no calibration number is given.

## Input

- File: `calibration_input_SYNTHETIC.jsonl` (sha256 `d4d487e60df63591903bd59360d869980b3241d4492683acbb9b0e91e13d1757`), 1600 rows
- Data label: synthetic: scripts/calibration_report.py --write-synthetic-input, seed 20261102, n 1600
- Seed 20261102, bootstrap resamples 500, confidence 0.95
- Declared minimum N (policy): min_n_report = 500, min_per_class = 50, min_n_fit = 300, isotonic_min_n = 800, min_n_threshold = 300, min_bin_count = 10

## Split

Seeded split by cluster: 799 rows to calibrate/select, 801 held out. Everything below is measured on the held-out part.

## Metrics

### Raw scores

- N = 801 (positive 473, negative 328)
- State: **estimate_reported**

| Metric | Value | 95% bootstrap interval |
|---|---|---|
| ECE, 10 equal-width bins | 0.1339 | [0.1108, 0.1706] |
| ECE, 10 equal-mass bins | 0.1376 | [0.1185, 0.1802] |
| MCE (equal-width; dominated by sparse bins) | 0.3377 | |
| Brier | 0.2588 | [0.2422, 0.2763] |
| Log loss | 0.7454 | [0.6996, 0.7983] |

Brier decomposition (equal-width): reliability 0.0238, resolution 0.0061, uncertainty 0.2418, within-bin -0.0007.

Reliability curve (equal-mass bins):

| Mean confidence | Observed frequency | Count |
|---|---|---|
| 0.2708 | 0.4568 | 81 |
| 0.4401 | 0.5125 | 80 |
| 0.5261 | 0.5250 | 80 |
| 0.5985 | 0.6375 | 80 |
| 0.6569 | 0.5750 | 80 |
| 0.7215 | 0.5125 | 80 |
| 0.7864 | 0.6500 | 80 |
| 0.8408 | 0.5875 | 80 |
| 0.8926 | 0.7250 | 80 |
| 0.9540 | 0.7250 | 80 |

- Warning: width-bin ECE: bins [0] hold fewer than 10 items

### Selective risk vs coverage (raw scores, held-out)

| Threshold | Coverage | Accepted | Errors | Error rate among accepted |
|---|---|---|---|---|
| 0.9986 | 0.0012 | 1 | 0 | 0.0000 |
| 0.9300 | 0.0811 | 65 | 15 | 0.2308 |
| 0.8980 | 0.1411 | 113 | 32 | 0.2832 |
| 0.8548 | 0.2210 | 177 | 49 | 0.2768 |
| 0.8236 | 0.2809 | 225 | 70 | 0.3111 |
| 0.7824 | 0.3608 | 289 | 91 | 0.3149 |
| 0.7454 | 0.4207 | 337 | 112 | 0.3323 |
| 0.6848 | 0.5006 | 401 | 145 | 0.3616 |
| 0.6384 | 0.5805 | 465 | 172 | 0.3699 |
| 0.6023 | 0.6404 | 513 | 186 | 0.3626 |
| 0.5477 | 0.7203 | 577 | 209 | 0.3622 |
| 0.4968 | 0.7803 | 625 | 239 | 0.3824 |
| 0.4369 | 0.8602 | 689 | 270 | 0.3919 |
| 0.3443 | 0.9201 | 737 | 293 | 0.3976 |
| 0.0715 | 1.0000 | 801 | 328 | 0.4095 |

## Recalibration

- Requested `auto`, result `platt` (fitted), fitted on 799 rows.

### Recalibrated scores (held-out)

- N = 801 (positive 473, negative 328)
- State: **estimate_reported**

| Metric | Value | 95% bootstrap interval |
|---|---|---|
| ECE, 10 equal-width bins | 0.0169 | [0.0138, 0.0617] |
| ECE, 10 equal-mass bins | 0.0385 | [0.0377, 0.0913] |
| MCE (equal-width; dominated by sparse bins) | 0.1048 | |
| Brier | 0.2358 | [0.2270, 0.2456] |
| Log loss | 0.6640 | [0.6448, 0.6852] |

Brier decomposition (equal-width): reliability 0.0006, resolution 0.0056, uncertainty 0.2418, within-bin -0.0010.

Reliability curve (equal-mass bins):

| Mean confidence | Observed frequency | Count |
|---|---|---|
| 0.4316 | 0.4568 | 81 |
| 0.5014 | 0.5125 | 80 |
| 0.5319 | 0.5250 | 80 |
| 0.5578 | 0.6375 | 80 |
| 0.5794 | 0.5750 | 80 |
| 0.6054 | 0.5125 | 80 |
| 0.6345 | 0.6500 | 80 |
| 0.6637 | 0.5875 | 80 |
| 0.6988 | 0.7250 | 80 |
| 0.7716 | 0.7250 | 80 |

- Warning: width-bin ECE: bins [9] hold fewer than 10 items

## Abstention thresholds

alpha = 0.3, delta = 0.1. Thresholds are chosen on the calibration part and measured on the held-out part.

### `ltt-bonferroni` (accepted_set_error)

- Threshold: n/a (abstain on everything)
- Calibration part: accepted 0 of 799, errors 0
- Held-out: accepted 0 of 801 (coverage 0.0000), error rate n/a, exact one-sided upper bound n/a at confidence 0.90
- Statement: With probability >= 1 - delta over the draw of the calibration set, the population error rate among accepted items, P(incorrect | confidence >= t), is <= alpha for the selected t (simultaneously valid for every t on the grid; Bonferroni over the grid, exact binomial p-values). If no grid threshold can be certified the decision abstains on everything.
- Assumptions: calibration items and future items are i.i.d. draws from one distribution (no covariate, label or temporal shift); the threshold grid was fixed before looking at the calibration labels; labels are correct (label noise is not modelled); the statement is about the population rate, not about any single item
- Note: no threshold could be certified: abstain on everything

### `crc-joint` (joint_false_accept_rate)

- Threshold: 0.5184
- Calibration part: accepted 653 of 799, errors 239
- Held-out: accepted 638 of 801 (coverage 0.7965), error rate 0.3840, exact one-sided upper bound 0.4097 at confidence 0.90
- Statement: If the n calibration items and the new item are exchangeable, the expected joint false-accept rate E[1{incorrect and confidence >= t}] is <= alpha for the selected t. This bounds the probability of accepting an incorrect item among ALL items, not the error rate among accepted items (that equals this rate divided by coverage and may exceed alpha). The expectation is also over the calibration draw, so it is an average guarantee, not a per-dataset one.
- Assumptions: calibration items and the new item are exchangeable (no distribution shift); loss 1[incorrect and accepted] is non-increasing in t and bounded by 1; labels are correct (label noise is not modelled)
- Note: upper_bound is the CRC-adjusted empirical joint risk, not an accepted-set error bound

## Per group

Each group is guarded separately; more groups means more comparisons (no correction is applied here).

| Group | N | State | ECE (mass) | Brier |
|---|---|---|---|---|
| A | 472 | uncalibrated_prior | withheld | withheld |
| B | 329 | uncalibrated_prior | withheld | withheld |

## Limits

- Bootstrap intervals are approximate; ECE is biased upward at small N.
- Statements about thresholds assume i.i.d. or exchangeable data; they do not hold under shift.
- Labels are taken as given (no label-noise model).

