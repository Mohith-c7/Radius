"""Unit tests for scripts/ci/zap_gate.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "zap_gate.py"
_spec = importlib.util.spec_from_file_location("zap_gate", _SCRIPT)
zg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = zg
_spec.loader.exec_module(zg)

REPORT = {
    "site": [
        {
            "@name": "http://x",
            "alerts": [
                {"pluginid": "10", "riskcode": "3", "name": "High one"},
                {"pluginid": "11", "riskcode": "2", "name": "Medium"},
                {"pluginid": "12", "riskcode": "3", "name": "High ignored"},
            ],
        }
    ]
}


def test_only_high_fails_and_ignore_works() -> None:
    assert len(zg.high_alerts(REPORT, set())) == 2
    found = zg.high_alerts(REPORT, zg.ignored_rules("# c\n12\tIGNORE\treason\n11\tWARN\n"))
    assert found == ["10: High one (http://x)"]


def test_empty_report_passes() -> None:
    assert zg.high_alerts({}, set()) == []


def test_repo_rules_file_has_no_entries_yet() -> None:
    rules = Path(__file__).resolve().parents[1] / ".zap" / "rules.tsv"
    assert zg.ignored_rules(rules.read_text(encoding="utf-8")) == set()
