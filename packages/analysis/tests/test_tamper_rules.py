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


# ---- replay 2026-11 false-positive fixes: severities, not just rule:check keys


def _case(case_id: str) -> dict:
    return next(c for c in CASES if c["id"] == case_id)


def _findings(case_id: str, rule: str):
    case = _case(case_id)
    report = analyze(case["base"], case["head"], case.get("config"), registry=case.get("registry"))
    return [f for f in report.findings if f.rule_id == rule]


@pytest.mark.parametrize(
    ("case_id", "severity"),
    [
        ("t002-runtime-skip", "high"),
        ("t002-if-false", "high"),
        ("t002-runtime-skip-new-test-unconditional", "medium"),
        ("t002-runtime-skip-data-dependent-condition", "medium"),
        ("t002-runtime-skip-platform-guard", "low"),
        ("t002-runtime-skip-optional-import", "low"),
        ("t002-runtime-skip-file-missing-guard-in-new-test", "low"),
    ],
)
def test_t002_runtime_skip_severity_follows_the_guard(case_id: str, severity: str) -> None:
    (finding,) = _findings(case_id, "T002")
    assert finding.severity.name.lower() == severity


def test_t013_collapsed_finding_says_how_many_and_stays_low() -> None:
    (finding,) = _findings("t013-many-noqa-in-one-file-collapse", "T013")
    assert "3 " in finding.reason and "suppressions" in finding.reason
    assert finding.severity.name.lower() == "low"
    assert len(finding.evidence) == 3
