"""EV-02: table-driven rule cases (true positive, true negative, near miss per rule)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from tamper_support import analyze, keys, load_cases  # noqa: E402

CASES = load_cases()


def test_case_table_is_large_enough_and_ids_unique() -> None:
    assert len(CASES) >= 80
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rule_case(case: dict) -> None:
    expected = sorted(case["expect"])
    report = analyze(
        case["base"], case["head"], case.get("config"), registry=case.get("registry")
    )
    assert report.rule_errors == ()
    assert keys(report) == expected, [f.reason for f in report.findings]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_same_findings_without_diff_text(case: dict) -> None:
    """Deriving changed lines from LK-01 hunks must match using the raw diff."""
    with_diff = analyze(case["base"], case["head"], case.get("config"), registry=case.get("registry"))
    without = analyze(
        case["base"], case["head"], case.get("config"), registry=case.get("registry"),
        with_diff=False,
    )
    assert [f.finding_id for f in without.findings] == [f.finding_id for f in with_diff.findings]
