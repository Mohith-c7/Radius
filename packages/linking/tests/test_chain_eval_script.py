"""scripts/link_chain_eval.py: metric helpers and a fixture-sanity run (LK-06).

The script (not the package) joins the criterion->symbol and symbol->test sides;
``radius_linking`` itself never imports ``radius_testing``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "link_chain_eval.py"
FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"

pytestmark = pytest.mark.skipif(
    not FIXTURES.is_dir(), reason="intent fixtures not present"
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("link_chain_eval_mod", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rank_metrics_hand_values(script):
    rankings = {
        "A": [("s", "t1"), ("s", "t2")],
        "B": [("s", "t9"), ("s", "t2")],
        "C": [],
    }
    gold = {"A": {("s", "t1")}, "B": {("s", "t2")}, "C": {("s", "t3")}, "D": set()}
    m = script.rank_metrics(rankings, gold)
    assert m == {"n": 3, "top1": 0.3333, "top3": 0.6667, "mrr": 0.5}
    assert script.rank_metrics({}, {})["n"] == 0


def test_fixture_run_is_labelled_deterministic_and_uncalibrated(script, capsys):
    assert script.main(["--json"]) == 0
    first = capsys.readouterr().out
    assert script.main(["--json"]) == 0
    assert capsys.readouterr().out == first
    report = json.loads(first)
    assert report["label"] == "fixture sanity, not a research result"
    assert report["score_kind"] == "link_confidence_uncalibrated"
    assert len(report["fixtures"]) >= 8
    agg = report["aggregate"]
    assert agg["gold_triples"] > 0 and 0.0 <= agg["triple_recall"] <= 1.0
    assert 0.0 <= agg["chain_rank"]["mrr"] <= 1.0
    assert "ece" in agg["chain_reliability"]


def test_calibrator_artifact_is_applied_only_when_given(script, tmp_path, capsys):
    from radius_linking.domain import fit_artifact

    art = fit_artifact("binning", [0.1, 0.4, 0.6, 0.9], [0, 0, 1, 1])
    path = tmp_path / "cal.json"
    path.write_text(art.to_json(), encoding="utf-8")
    out = tmp_path / "report.json"
    assert script.main(["--calibrator", str(path), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "link_confidence_calibrated" in text and "fixture sanity" in text
    assert (
        json.loads(out.read_text(encoding="utf-8"))["score_kind"]
        == "link_confidence_calibrated"
    )
