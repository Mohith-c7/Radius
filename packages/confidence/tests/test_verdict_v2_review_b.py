"""Regression tests for the code review B findings (B-01 and rule-level items)."""

from __future__ import annotations

import pytest
from radius_confidence.verdict_v2.application.service import (
    build_criterion_verdict,
    compute_verdict_v2,
)
from radius_confidence.verdict_v2.domain.model import Verdict
from radius_confidence.verdict_v2.domain.rules import AnalysisFacts
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.inputs import CriterionInput
from radius_evidence.domain.quality import EvidenceQuality
from radius_evidence.domain.states import evaluate_criterion
from radius_evidence.domain.support import compute_support

CFG = VerdictV2Config()
HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"


def _row(eid: str, status: str) -> EvidenceQuality:
    return EvidenceQuality(
        evidence_id=eid, criterion_id="c1", a_static=1.0, d_eff=0.6, cap_static=0.6, i=0.8,
        f=1.0, flaky_f=1.0, tamper_penalty=0.0, q=0.4, l_cs=1.0, l_st=0.9, r_ct=1.0, l=0.9,
        term=0.4, status=status, group_symbol="s",
    )


def _verdict(n_failing: int, n_passing: int = 1):
    crit = CriterionInput("c1", "text", 1.0, "behavioral_testable", "confirmed")
    rows = [_row(f"ev_f{i:03d}", "gated:outcome_failed") for i in range(n_failing)]
    rows += [_row(f"ev_p{i:03d}", "counted") for i in range(n_passing)]
    sup = compute_support("c1", rows, CFG.support)
    st = evaluate_criterion(crit, sup, CFG, results_received=True)
    cv = build_criterion_verdict(crit, sup, st)
    return cv, None


@pytest.mark.parametrize("n_failing", [1, 2, 3, 7, 60])
def test_b01_many_failing_linked_tests_do_not_crash_and_fail(n_failing: int) -> None:
    from radius_confidence.verdict_v2.domain.model import CriterionVerdict  # noqa: F401
    from radius_evidence.domain.states import UimResult

    cv, _ = _verdict(n_failing)
    uim = UimResult(1.0, 1.0, 1.0, 1.0, ("c1",), ())
    v = compute_verdict_v2(
        analysis_id="an-1", head_sha=HEAD, revision=1, criteria=[cv], uim=uim,
        facts=AnalysisFacts(results_received=True, behavioral_symbols=1, ci_failed_cases=0),
        config=CFG,
    )
    assert v.verdict == Verdict.FAILED
    r1a = next(r for r in v.justification["rules"] if r["id"] == "R1a")
    ids = r1a["refs"]["evidence_ids"]
    assert isinstance(ids, list) and len(ids) == n_failing
    assert all("," not in i for i in ids)
    assert ids == sorted(ids)


def test_b01_reason_ref_is_one_id_and_refs_is_a_tuple() -> None:
    cv, _ = _verdict(3)
    reason = cv.reasons[0]
    assert reason.ref == "ev_f000"
    assert reason.refs == ("ev_f000", "ev_f001", "ev_f002")
    assert cv.to_dict()["reasons"][0]["refs"] == ["ev_f000", "ev_f001", "ev_f002"]


def test_b01_single_failing_test_keeps_the_old_bytes() -> None:
    cv, _ = _verdict(1)
    assert "refs" not in cv.to_dict()["reasons"][0]


def test_b10_docs_only_change_is_not_pending_and_not_applicable() -> None:
    from radius_confidence.verdict_v2.domain.model import Verdict as V

    facts = AnalysisFacts(results_received=False, behavioral_symbols=0, inert_changes_only=True)
    from radius_evidence.domain.states import UimResult

    v = compute_verdict_v2(
        analysis_id="an-1", head_sha=HEAD, revision=1, criteria=[],
        uim=UimResult(0.0, 0.0, 0.0, 1.0, (), ()), facts=facts, config=CFG,
    )
    assert v.verdict == V.INSUFFICIENT_EVIDENCE
    assert v.pending is False
    assert v.justification["decided_by"] == "R2e"
    r2e = next(r for r in v.justification["rules"] if r["id"] == "R2e")
    assert r2e["inputs"]["not_applicable"] is True


def test_b10_a_blocking_marker_keeps_a_docs_change_pending_and_not_inert() -> None:
    from radius_evidence.domain.states import UimResult

    facts = AnalysisFacts(
        results_received=False, behavioral_symbols=0, inert_changes_only=True,
        degraded=("unanalyzed_files:1",),
    )
    v = compute_verdict_v2(
        analysis_id="an-1", head_sha=HEAD, revision=1, criteria=[],
        uim=UimResult(0.0, 0.0, 0.0, 1.0, (), ()), facts=facts, config=CFG,
    )
    assert v.pending is True and v.justification["decided_by"] == "R2p"
