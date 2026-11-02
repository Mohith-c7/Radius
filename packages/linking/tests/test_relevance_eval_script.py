"""scripts/relevance_eval.py: fixture sanity run for r_ct (VS-04).

The numbers are a fixture sanity check, not a research result.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "relevance_eval.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("relevance_eval_mod", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def results(mod):
    loader = mod._load_loader()
    return {f.id: mod.evaluate_fixture(f, 0.3) for f in loader.discover()}


def test_all_eight_fixtures_evaluated(results):
    assert len(results) == 8


def test_fixture_08_untested_criterion_gets_no_credit(results):
    r = results["08_multi_criterion_partial_evidence"]
    assert "C4" in r["criteria_without_gold_tests"]
    assert not [p for p in r["predicted"] if p[0] == "C4"]
    assert {k: v for k, v in r["scores"].items() if k.startswith("C4|")} == {
        k: 0.0 for k in r["scores"] if k.startswith("C4|")
    }
    assert r["fn"] == 0 and r["fp"] == 0


def test_fixture_02_unevidenced_criterion_gets_no_credit(results):
    r = results["02_correct_weak_tests"]
    assert not [p for p in r["predicted"] if p[0] == "C2"]
    assert all(v < 0.3 for k, v in r["scores"].items() if k.startswith("C2|"))


def test_relevance_cuts_false_credit_versus_symbol_only_baseline(mod, results):
    summary = mod.aggregate(list(results.values()))
    assert summary["label"] == "fixture sanity, not a research result"
    assert summary["r_ct"]["precision"] > summary["baseline_all_connected"]["precision"]
    assert summary["r_ct"]["fp"] < summary["baseline_all_connected"]["fp"]


def test_pr_helper_edges(mod):
    assert mod._pr(0, 0, 0) == (1.0, 1.0)
    assert mod._pr(1, 1, 2) == (0.5, 0.3333)


def test_main_json_and_text(mod, tmp_path, capsys):
    out = tmp_path / "r.json"
    assert mod.main(["--json", "--out", str(out)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["label"].startswith("fixture sanity")
    assert json.loads(out.read_text(encoding="utf-8")) == data
    assert mod.main([]) == 0
    assert "fixture sanity, not a research result" in capsys.readouterr().out
