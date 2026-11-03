"""scripts/calibration_report.py: guard, determinism, input handling, committed synthetic example."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calibration_report as cr  # noqa: E402

EXAMPLES = ROOT / "docs" / "research" / "examples"
EXAMPLE_ARGS = [
    "--seed", "20261102", "--min-n-report", "500", "--min-per-class", "50", "--split", "0.5",
    "--recalibrate", "auto", "--min-n-fit", "300", "--isotonic-min-n", "800", "--alpha", "0.3",
    "--min-n-threshold", "300", "--resamples", "500", "--synthetic", "--data-label",
    "synthetic: scripts/calibration_report.py --write-synthetic-input, seed 20261102, n 1600",
]


def _lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_synthetic_rows_are_deterministic_and_valid():
    a, b = cr.synthetic_rows(50, 1), cr.synthetic_rows(50, 1)
    assert a == b and a != cr.synthetic_rows(50, 2)
    assert all(0.0 <= r["prediction"] <= 1.0 and r["label"] in (0, 1) for r in a)


def test_small_input_is_withheld_with_no_calibration_number(tmp_path):
    inp = _write_jsonl(tmp_path / "in.jsonl", cr.synthetic_rows(120, 3))
    out = tmp_path / "out"
    rc = cr.main(["--input", str(inp), "--out-dir", str(out), "--seed", "1",
                  "--min-n-report", "500", "--min-per-class", "20", "--synthetic"])
    assert rc == 0
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["not_a_research_result"] is True and rep["synthetic"] is True
    assert rep["raw"]["state"] == "uncalibrated_prior" and rep["raw"]["metrics"] is None
    assert rep["risk_coverage"] is None
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "SYNTHETIC DATA. Not a research result." in md and "Withheld: N=120" in md
    assert "| ECE, " not in md  # no metrics table at all


def test_report_is_deterministic_and_has_metrics_above_minimum(tmp_path):
    inp = _write_jsonl(tmp_path / "in.jsonl", cr.synthetic_rows(700, 4))
    args = ["--input", str(inp), "--seed", "9", "--min-n-report", "300", "--min-per-class", "30",
            "--resamples", "40"]
    for name in ("a", "b"):
        assert cr.main([*args, "--out-dir", str(tmp_path / name)]) == 0
    assert (tmp_path / "a" / "report.json").read_bytes() == (tmp_path / "b" / "report.json").read_bytes()
    rep = json.loads((tmp_path / "a" / "report.json").read_text(encoding="utf-8"))
    assert rep["raw"]["state"] == "estimate_reported"
    assert rep["raw"]["metrics"]["ece_width"]["ci"]["seed"] == 9
    assert rep["synthetic"] is False  # not labelled synthetic unless the flag is passed
    md = (tmp_path / "a" / "report.md").read_text(encoding="utf-8")
    assert "Not a research result" in md and "SYNTHETIC DATA" not in md
    assert set(rep["groups"]) == {"A", "B"}


def test_csv_input_and_label_spellings(tmp_path):
    p = tmp_path / "in.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["prediction", "label", "group"])
        for i in range(40):
            w.writerow([f"{(i % 10) / 10:.1f}", "true" if i % 2 else "False", "g"])
    rows = cr.read_rows(p, {"prediction": "prediction", "label": "label", "group": "group", "cluster": "cluster"})
    assert len(rows) == 40 and {r["label"] for r in rows} == {0, 1} and rows[0]["group"] == "g"


def test_invalid_rows_fail_loudly(tmp_path, capsys):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"prediction": 1.5, "label": 1}\n{"prediction": 0.2, "label": "maybe"}\n', encoding="utf-8")
    rc = cr.main(["--input", str(p), "--out-dir", str(tmp_path / "o"), "--seed", "1",
                  "--min-n-report", "10", "--min-per-class", "1"])
    assert rc == 2 and "2 invalid row(s)" in capsys.readouterr().err


def test_selection_without_a_split_is_refused(tmp_path):
    inp = _write_jsonl(tmp_path / "in.jsonl", cr.synthetic_rows(100, 1))
    with pytest.raises(SystemExit) as exc:
        cr.main(["--input", str(inp), "--out-dir", str(tmp_path / "o"), "--seed", "1",
                 "--min-n-report", "10", "--min-per-class", "1", "--alpha", "0.1",
                 "--min-n-threshold", "10"])
    assert exc.value.code == 2


def test_split_keeps_clusters_together_and_is_seeded():
    rows = cr.synthetic_rows(300, 5)
    cal, ev = cr.split_rows(rows, 0.5, 7)
    assert {r["cluster"] for r in cal}.isdisjoint({r["cluster"] for r in ev})
    assert len(cal) + len(ev) == 300
    assert cr.split_rows(rows, 0.5, 7) == (cal, ev)
    assert cr.split_rows(rows, 0.5, 8) != (cal, ev)


def test_committed_example_is_synthetic_labelled_and_reproducible(tmp_path):
    inp = EXAMPLES / "calibration_input_SYNTHETIC.jsonl"
    regenerated = tmp_path / "regen.jsonl"
    assert cr.main(["--write-synthetic-input", str(regenerated), "--synthetic-n", "1600",
                    "--seed", "20261102"]) == 0
    assert _lf(regenerated) == _lf(inp)

    out = tmp_path / "out"
    assert cr.main(["--input", str(inp), "--out-dir", str(out), *EXAMPLE_ARGS]) == 0
    assert _lf(out / "report.md") == _lf(EXAMPLES / "calibration_report_SYNTHETIC.md")
    committed = json.loads(_lf(EXAMPLES / "calibration_report_SYNTHETIC.json"))
    assert json.loads(_lf(out / "report.json")) == committed
    assert committed["synthetic"] is True and committed["not_a_research_result"] is True
    assert committed["input"]["sha256"] == hashlib.sha256(_lf(inp).encode()).hexdigest()
    assert _lf(EXAMPLES / "calibration_report_SYNTHETIC.md").startswith(
        "# Calibration report\n\n> **SYNTHETIC DATA. Not a research result.**"
    )
