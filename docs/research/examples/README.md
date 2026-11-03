# Examples (synthetic)

Everything here is **synthetic** and exists only to show the shape of the tools' output. None of it is a research result, and no number in these files says anything about Radius or any real model.

## Calibration report

Files: `calibration_input_SYNTHETIC.jsonl` (1,600 invented rows: a score drawn from Beta(3, 1.5), an outcome drawn from a deliberately different probability so the score is miscalibrated, two groups, clusters of three rows), `calibration_report_SYNTHETIC.md`, `calibration_report_SYNTHETIC.json`.

Reproduce (from the repository root; output is deterministic, so `tests/test_calibration_report.py` regenerates it and compares):

```
python scripts/calibration_report.py --write-synthetic-input docs/research/examples/calibration_input_SYNTHETIC.jsonl --synthetic-n 1600 --seed 20261102
python scripts/calibration_report.py --input docs/research/examples/calibration_input_SYNTHETIC.jsonl --out-dir OUT \
    --seed 20261102 --min-n-report 500 --min-per-class 50 --split 0.5 --recalibrate auto --min-n-fit 300 \
    --isotonic-min-n 800 --alpha 0.3 --min-n-threshold 300 --resamples 500 --synthetic \
    --data-label "synthetic: scripts/calibration_report.py --write-synthetic-input, seed 20261102, n 1600"
```

The minimum-N values in that command are arbitrary values chosen for a small example. They are **not** the pre-registration's values and not a recommendation. What the example shows: the guard withholding the per-group numbers (each group is below the declared minimum), a recalibrator fitted on one part and measured on the other, and that the two abstention procedures bound different quantities (the conformal-risk-control threshold gives a held-out error among accepted well above `alpha`, because it controls the joint false-accept rate; see `docs/research/evaluation/CALIBRATION_TOOLKIT.md`).
