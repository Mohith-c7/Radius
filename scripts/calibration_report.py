#!/usr/bin/env python
"""Calibration report for a file of (prediction, label[, group]) rows (CA-05 groundwork).

    python scripts/calibration_report.py --input preds.jsonl --out-dir out/ \\
        --min-n-report 2000 --min-per-class 50 --seed 20261102 [--synthetic]
    # with a disjoint calibration half for recalibration and abstention thresholds:
    python scripts/calibration_report.py --input preds.csv --out-dir out/ ... \\
        --split 0.5 --recalibrate auto --alpha 0.10 --min-n-fit 500 \\
        --isotonic-min-n 1000 --min-n-threshold 500

Input: JSONL (one object per line) or CSV with a header. Columns: ``prediction``
(probability in [0, 1] that the label is 1), ``label`` (0/1/true/false), optional
``group`` (per-group tables) and ``cluster`` (resampling unit for bootstrap and
for the split, for example the task instance). Names can be changed with
``--prediction-field`` etc.

Writes ``report.json`` and ``report.md`` to ``--out-dir``. Output is deterministic
(no timestamps, seeded). Every report states that it is not a research result;
below the declared minimum N it contains no calibration number at all.

The minimum-N flags are required on purpose: they are analysis choices that
belong in the pre-registration, not defaults hidden in a script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SRC = str(ROOT / "packages" / "confidence" / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from radius_confidence.calibration import (  # noqa: E402
    CalibrationPolicy,
    evaluate_calibration,
    evaluate_threshold,
    fit_calibrator,
    risk_coverage_curve,
    select_threshold,
)
from radius_confidence.calibration._validate import CalibrationInputError  # noqa: E402

TOOL_VERSION = "calibration-report-v1"
_TRUE = {"1", "true", "yes", "y"}
_FALSE = {"0", "false", "no", "n"}


class InputError(ValueError):
    pass


def _parse_label(raw: object) -> int:
    if isinstance(raw, bool):
        return int(raw)
    s = str(raw).strip().lower()
    if s in _TRUE:
        return 1
    if s in _FALSE:
        return 0
    if s in ("1.0", "0.0"):
        return int(float(s))
    raise ValueError(f"label must be 0/1/true/false, got {raw!r}")


def synthetic_rows(n: int, seed: int) -> list[dict]:
    """Deterministic SYNTHETIC rows with a deliberately miscalibrated score.

    Score ~ Beta(3, 1.5); the true event probability is ``0.2 + 0.6 * score``
    for group ``A`` and ``0.3 + 0.4 * score`` for group ``B`` (so the score is
    overconfident at both ends). Three rows share a ``cluster``. These numbers are
    invented to exercise the tool; they say nothing about any real model.
    """

    rng = random.Random(seed)
    rows = []
    for i in range(n):
        score = round(rng.betavariate(3.0, 1.5), 6)
        group = "A" if rng.random() < 0.6 else "B"
        p = 0.2 + 0.6 * score if group == "A" else 0.3 + 0.4 * score
        rows.append({"prediction": score, "label": int(rng.random() < p),
                     "group": group, "cluster": f"c{i // 3}"})
    return rows


def read_rows(path: Path, fields: dict[str, str]) -> list[dict]:
    """Read and validate rows; raises :class:`InputError` listing the first problems."""

    text = path.read_text(encoding="utf-8-sig")
    raw_rows: list[tuple[int, dict]] = []
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(text.splitlines())
        for i, row in enumerate(reader, start=2):
            raw_rows.append((i, dict(row)))
    else:
        for i, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputError(f"line {i}: invalid JSON ({exc.msg})") from None
            if not isinstance(obj, dict):
                raise InputError(f"line {i}: expected an object")
            raw_rows.append((i, obj))
    rows: list[dict] = []
    errors: list[str] = []
    for lineno, obj in raw_rows:
        try:
            if fields["prediction"] not in obj or fields["label"] not in obj:
                raise ValueError(f"missing {fields['prediction']!r} or {fields['label']!r}")
            pred = float(obj[fields["prediction"]])
            if not 0.0 <= pred <= 1.0:
                raise ValueError(f"prediction {pred} outside [0, 1]")
            row = {"prediction": pred, "label": _parse_label(obj[fields["label"]])}
            grp = obj.get(fields["group"])
            cl = obj.get(fields["cluster"])
            row["group"] = None if grp in (None, "") else str(grp)
            row["cluster"] = None if cl in (None, "") else str(cl)
            rows.append(row)
        except (ValueError, TypeError) as exc:
            errors.append(f"row {lineno}: {exc}")
    if errors:
        shown = "; ".join(errors[:10])
        raise InputError(f"{len(errors)} invalid row(s): {shown}")
    if not rows:
        raise InputError("no rows")
    return rows


def split_rows(rows: list[dict], fraction: float, seed: int) -> tuple[list[dict], list[dict]]:
    """Seeded split into (calibration, evaluation); whole clusters stay together."""

    rng = random.Random(seed)
    if any(r["cluster"] is not None for r in rows):
        keys = sorted({r["cluster"] if r["cluster"] is not None else f"__row{i}" for i, r in enumerate(rows)})
        rng.shuffle(keys)
        cut = set(keys[: round(len(keys) * fraction)])
        cal, ev = [], []
        for i, r in enumerate(rows):
            key = r["cluster"] if r["cluster"] is not None else f"__row{i}"
            (cal if key in cut else ev).append(r)
        return cal, ev
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    k = round(len(rows) * fraction)
    chosen = set(idx[:k])
    return [rows[i] for i in sorted(chosen)], [r for i, r in enumerate(rows) if i not in chosen]


def _cols(rows: list[dict]) -> tuple[list[float], list[int], list[str] | None]:
    clusters = [r["cluster"] for r in rows]
    return (
        [r["prediction"] for r in rows],
        [r["label"] for r in rows],
        None if all(c is None for c in clusters) else [c if c is not None else f"__row{i}" for i, c in enumerate(clusters)],
    )


def _subsample(points: list[dict], k: int = 15) -> list[dict]:
    if len(points) <= k:
        return points
    step = (len(points) - 1) / (k - 1)
    keep = sorted({round(i * step) for i in range(k)})
    return [points[i] for i in keep]


def build_report(rows: list[dict], args: argparse.Namespace, input_sha256: str) -> dict:
    policy = CalibrationPolicy(
        min_n_report=args.min_n_report,
        min_per_class=args.min_per_class,
        min_n_fit=args.min_n_fit,
        isotonic_min_n=args.isotonic_min_n,
        min_n_threshold=args.min_n_threshold,
        min_bin_count=args.min_bin_count,
    )
    kw = {"seed": args.seed, "n_bins": args.n_bins, "n_resamples": args.resamples, "confidence": args.confidence}
    report: dict = {
        "tool": TOOL_VERSION,
        "not_a_research_result": True,
        "synthetic": bool(args.synthetic),
        "data_label": args.data_label,
        "input": {"file": Path(args.input).name, "sha256": input_sha256, "rows": len(rows)},
        "args": {
            "seed": args.seed, "n_bins": args.n_bins, "resamples": args.resamples,
            "confidence": args.confidence, "split": args.split, "recalibrate": args.recalibrate,
            "alpha": args.alpha, "delta": args.delta,
        },
        "policy": policy.to_dict(),
    }

    eval_rows = rows
    cal_rows: list[dict] = []
    if args.split is not None:
        cal_rows, eval_rows = split_rows(rows, args.split, args.seed)
        report["split"] = {
            "fraction_calibration": args.split,
            "n_calibration": len(cal_rows),
            "n_evaluation": len(eval_rows),
            "unit": "cluster" if any(r["cluster"] for r in rows) else "row",
        }

    ps, ys, clusters = _cols(eval_rows)
    report["raw"] = evaluate_calibration(ps, ys, policy, clusters=clusters, **kw)
    curve = [p.to_dict() for p in risk_coverage_curve(ps, ys)] if len(ps) >= args.min_n_report else None
    report["risk_coverage"] = None if curve is None else _subsample(curve, 51)
    report["risk_coverage_total_points"] = None if curve is None else len(curve)

    conf_for_threshold = ps
    fitted = None
    if args.recalibrate:
        cps, cys, _ = _cols(cal_rows)
        cal = fit_calibrator(args.recalibrate, cps, cys, policy)
        entry = {
            "requested": args.recalibrate,
            "kind": cal.kind,
            "state": cal.state.value,
            "n_fit": cal.n_fit,
            "reason": getattr(cal, "reason", None),
        }
        if cal.state.value == "fitted":
            adj = [c.value for c in cal.calibrate_many(ps)]
            entry["held_out"] = evaluate_calibration(adj, ys, policy, clusters=clusters, **kw)
            conf_for_threshold = adj
            fitted = cal
        report["recalibration"] = entry

    if args.alpha is not None:
        cps, cys, _ = _cols(cal_rows)
        if fitted is not None:
            cps = [c.value for c in fitted.calibrate_many(cps)]
        thresholds = {}
        for method in ("ltt", "crc"):
            d = select_threshold(method, cps, cys, args.alpha, policy, delta=args.delta)
            held = evaluate_threshold(conf_for_threshold, ys, d.threshold, delta=args.delta)
            thresholds[method] = {"decision": d.to_dict(), "held_out": held}
        report["thresholds"] = thresholds

    groups = sorted({r["group"] for r in eval_rows if r["group"] is not None})
    if groups:
        per_group = {}
        for g in groups:
            sub = [r for r in eval_rows if r["group"] == g]
            gp, gy, gc = _cols(sub)
            per_group[g] = evaluate_calibration(gp, gy, policy, clusters=gc, **kw)
        report["groups"] = per_group
    return report


# ------------------------------------------------------------------ markdown


def _f(v: object, nd: int = 4) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def _ci(m: dict) -> str:
    c = m["ci"]
    return f"[{_f(c['lower'])}, {_f(c['upper'])}]" if c["lower"] is not None else "n/a"


def _metrics_md(rep: dict, title: str) -> list[str]:
    out = [f"### {title}", "", f"- N = {rep['n']} (positive {rep['n_positive']}, negative {rep['n_negative']})",
           f"- State: **{rep['state']}**"]
    if rep["metrics"] is None:
        out += [f"- Withheld: {r}" for r in rep["reasons"]]
        out.append("")
        return out
    m = rep["metrics"]
    out += ["", "| Metric | Value | 95% bootstrap interval |", "|---|---|---|"]
    out.append(f"| ECE, {m['n_bins']} equal-width bins | {_f(m['ece_width']['value'])} | {_ci(m['ece_width'])} |")
    out.append(f"| ECE, {m['n_bins']} equal-mass bins | {_f(m['ece_mass']['value'])} | {_ci(m['ece_mass'])} |")
    out.append(f"| MCE (equal-width; dominated by sparse bins) | {_f(m['ece_width']['mce'])} | |")
    out.append(f"| Brier | {_f(m['brier']['value'])} | {_ci(m['brier'])} |")
    out.append(f"| Log loss | {_f(m['log_loss']['value'])} | {_ci(m['log_loss'])} |")
    d = m["brier"]["decomposition_width"]
    out += ["", f"Brier decomposition (equal-width): reliability {_f(d['reliability'])}, resolution "
            f"{_f(d['resolution'])}, uncertainty {_f(d['uncertainty'])}, within-bin {_f(d['within_bin'])}.", ""]
    out += ["Reliability curve (equal-mass bins):", "", "| Mean confidence | Observed frequency | Count |", "|---|---|---|"]
    out += [f"| {_f(p['mean_confidence'])} | {_f(p['observed_frequency'])} | {p['count']} |"
            for p in m["reliability_curve_mass"]]
    out += [""] + [f"- Warning: {w}" for w in rep["warnings"]]
    out.append("")
    return out


def render_markdown(rep: dict) -> str:
    lines = ["# Calibration report", ""]
    if rep["synthetic"]:
        lines += ["> **SYNTHETIC DATA. Not a research result.** The input was generated to exercise this tool.", ""]
    lines += [
        "> **Not a research result.** This report describes only the file supplied, using the tool "
        f"`{rep['tool']}`. It makes no claim that any model or product score is calibrated. The state "
        "`estimate_reported` means only that N reached the declared minimum; `uncalibrated_prior` means "
        "the data are too few and no calibration number is given.", "",
        "## Input", "",
        f"- File: `{rep['input']['file']}` (sha256 `{rep['input']['sha256']}`), {rep['input']['rows']} rows",
        f"- Data label: {rep['data_label']}",
        f"- Seed {rep['args']['seed']}, bootstrap resamples {rep['args']['resamples']}, "
        f"confidence {rep['args']['confidence']}",
        "- Declared minimum N (policy): " + ", ".join(f"{k} = {v}" for k, v in rep["policy"].items()), "",
    ]
    if "split" in rep:
        s = rep["split"]
        lines += ["## Split", "",
                  f"Seeded split by {s['unit']}: {s['n_calibration']} rows to calibrate/select, "
                  f"{s['n_evaluation']} held out. Everything below is measured on the held-out part.", ""]
    lines += ["## Metrics", ""] + _metrics_md(rep["raw"], "Raw scores")
    if rep.get("risk_coverage"):
        lines += ["### Selective risk vs coverage (raw scores, held-out)", "",
                  "| Threshold | Coverage | Accepted | Errors | Error rate among accepted |", "|---|---|---|---|---|"]
        lines += [f"| {_f(p['threshold'])} | {_f(p['coverage'])} | {p['n_accepted']} | {p['n_errors']} | {_f(p['risk'])} |"
                  for p in _subsample(rep["risk_coverage"])]
        lines.append("")
    if "recalibration" in rep:
        r = rep["recalibration"]
        lines += ["## Recalibration", "", f"- Requested `{r['requested']}`, result `{r['kind']}` ({r['state']}), fitted on {r['n_fit']} rows."]
        if r.get("reason"):
            lines.append(f"- Not fitted: {r['reason']}")
        lines.append("")
        if "held_out" in r:
            lines += _metrics_md(r["held_out"], "Recalibrated scores (held-out)")
    if "thresholds" in rep:
        lines += ["## Abstention thresholds", "",
                  f"alpha = {rep['args']['alpha']}, delta = {rep['args']['delta']}. Thresholds are chosen on the "
                  "calibration part and measured on the held-out part.", ""]
        for method, t in rep["thresholds"].items():
            d, h = t["decision"], t["held_out"]
            lines += [f"### `{d['method']}` ({d['risk_kind']})", "",
                      f"- Threshold: {_f(d['threshold'])}" + (" (abstain on everything)" if d["abstains_on_everything"] else ""),
                      f"- Calibration part: accepted {d['n_accepted_cal']} of {d['n_cal']}, errors {d['errors_cal']}",
                      f"- Held-out: accepted {h['n_accepted']} of {h['n']} (coverage {_f(h['coverage'])}), "
                      f"error rate {_f(h['error_rate'])}, exact one-sided upper bound {_f(h['error_upper_bound'])} "
                      f"at confidence {_f(h['bound_confidence'], 2)}",
                      f"- Statement: {d['guarantee']}", "- Assumptions: " + "; ".join(d["assumptions"]),
                      f"- Note: {d['note']}" if d["note"] else "", ""]
    if "groups" in rep:
        lines += ["## Per group", "", "Each group is guarded separately; more groups means more comparisons "
                  "(no correction is applied here).", "", "| Group | N | State | ECE (mass) | Brier |", "|---|---|---|---|---|"]
        for g, r in rep["groups"].items():
            m = r["metrics"]
            lines.append(f"| {g} | {r['n']} | {r['state']} | {_f(m['ece_mass']['value']) if m else 'withheld'} | "
                         f"{_f(m['brier']['value']) if m else 'withheld'} |")
        lines.append("")
    lines += ["## Limits", "",
              "- Bootstrap intervals are approximate; ECE is biased upward at small N.",
              "- Statements about thresholds assume i.i.d. or exchangeable data; they do not hold under shift.",
              "- Labels are taken as given (no label-noise model).", ""]
    return "\n".join(line for line in lines if line is not None) + "\n"


def main(argv: list[str] | None = None) -> int:
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--write-synthetic-input")
    pre.add_argument("--synthetic-n", type=int, default=3000)
    pre.add_argument("--seed", type=int)
    known, _ = pre.parse_known_args(argv)
    if known.write_synthetic_input:
        if known.seed is None:
            print("error: --write-synthetic-input needs --seed", file=sys.stderr)
            return 2
        out_path = Path(known.write_synthetic_input)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in synthetic_rows(known.synthetic_n, known.seed):
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {known.synthetic_n} SYNTHETIC rows to {out_path}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--min-n-report", type=int, required=True, help="declared minimum N to report any number")
    ap.add_argument("--min-per-class", type=int, required=True)
    ap.add_argument("--min-n-fit", type=int, default=None)
    ap.add_argument("--isotonic-min-n", type=int, default=None)
    ap.add_argument("--min-n-threshold", type=int, default=None)
    ap.add_argument("--min-bin-count", type=int, default=10)
    ap.add_argument("--n-bins", type=int, default=10)
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--confidence", type=float, default=0.95)
    ap.add_argument("--split", type=float, default=None, help="fraction of rows (or clusters) for fitting/selection")
    ap.add_argument("--recalibrate", choices=["auto", "isotonic", "platt"], default=None)
    ap.add_argument("--alpha", type=float, default=None, help="target error among accepted; needs --split")
    ap.add_argument("--delta", type=float, default=0.10)
    ap.add_argument("--synthetic", action="store_true", help="mark the report as built from synthetic data")
    ap.add_argument("--data-label", default="unspecified")
    ap.add_argument("--prediction-field", default="prediction")
    ap.add_argument("--label-field", default="label")
    ap.add_argument("--group-field", default="group")
    ap.add_argument("--cluster-field", default="cluster")
    ap.add_argument("--write-synthetic-input", metavar="PATH", help="write SYNTHETIC rows (JSONL) and exit")
    ap.add_argument("--synthetic-n", type=int, default=3000)
    args = ap.parse_args(argv)

    needs_fit = args.recalibrate is not None or args.alpha is not None
    if needs_fit and args.split is None:
        ap.error("--recalibrate and --alpha need --split so selection and evaluation use disjoint data")
    if args.split is not None and not 0.0 < args.split < 1.0:
        ap.error("--split must be in (0, 1)")
    if args.recalibrate and args.min_n_fit is None:
        ap.error("--recalibrate needs --min-n-fit (and --isotonic-min-n)")
    if args.recalibrate and args.isotonic_min_n is None:
        ap.error("--recalibrate needs --isotonic-min-n")
    if args.alpha is not None and args.min_n_threshold is None:
        ap.error("--alpha needs --min-n-threshold")
    # unused policy fields still need a value; make them inert but explicit in the report
    for name in ("min_n_fit", "isotonic_min_n", "min_n_threshold"):
        if getattr(args, name) is None:
            setattr(args, name, args.min_n_report)

    path = Path(args.input)
    fields = {"prediction": args.prediction_field, "label": args.label_field,
              "group": args.group_field, "cluster": args.cluster_field}
    try:
        rows = read_rows(path, fields)
        report = build_report(rows, args, hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
    except (InputError, CalibrationInputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {out / 'report.md'} and {out / 'report.json'} (state: {report['raw']['state']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
