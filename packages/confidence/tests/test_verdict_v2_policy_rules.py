"""Verdict v2 contract 3: rules P1/P2, policy/waiver blocks on the verdict, degraded markers."""

from __future__ import annotations

from typing import Any

import pytest
from radius_confidence.verdict_v2.application.service import compute_verdict_v2
from radius_confidence.verdict_v2.domain.model import (
    POLICY_RULE_ORDER,
    RULE_ORDER,
    CriterionVerdict,
    Verdict,
    VerdictV2,
)
from radius_confidence.verdict_v2.domain.rules import (
    RULE_TABLE,
    AnalysisFacts,
    evaluate_rules,
    is_blocking_degraded,
)
from radius_confidence.verdict_v2.domain.tree import check_justification
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.enums import SupportState
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.states import UimResult

HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"


def crit(cid: str = "c1", state: SupportState = SupportState.PROVEN) -> CriterionVerdict:
    return CriterionVerdict(
        criterion_id=cid, text="t", weight=1.0, testability="behavioral_testable",
        lifecycle="confirmed", state=state, S=0.6, S_raw=0.6,
    )


def uim(criteria: list[CriterionVerdict]) -> UimResult:
    return UimResult(0.0, 0.0, float(len(criteria)), 1.0, (), ())


def run(**kw: Any) -> VerdictV2:
    facts_kw: dict[str, Any] = {"results_received": True, "behavioral_symbols": 1}
    extra = {k: kw.pop(k) for k in ("policy", "waivers", "tamper_waived") if k in kw}
    facts_kw.update(kw)
    criteria = [crit()]
    return compute_verdict_v2(
        analysis_id="a", head_sha=HEAD, revision=1, criteria=criteria, uim=uim(criteria),
        facts=AnalysisFacts(**facts_kw), **extra,
    )


def fired(v: VerdictV2) -> list[str]:
    return [r["id"] for r in v.justification["rules"] if r["fired"]]


def test_without_a_policy_the_rule_list_is_unchanged() -> None:
    v = run()
    assert [r["id"] for r in v.justification["rules"]] == list(RULE_ORDER)
    assert v.policy == {} and v.waivers == {} and v.tamper_waived == ()
    assert "policy" not in v.justification and "waivers" not in v.justification


def test_policy_rules_sit_between_r2d_and_r3a() -> None:
    assert POLICY_RULE_ORDER.index("P1") == POLICY_RULE_ORDER.index("R2d") + 1
    assert POLICY_RULE_ORDER.index("P2") == POLICY_RULE_ORDER.index("R3a") - 1
    assert [r for r in POLICY_RULE_ORDER if r not in ("P1", "P2")] == list(RULE_ORDER)
    v = run(policy_rules=True)
    assert [r["id"] for r in v.justification["rules"]] == list(POLICY_RULE_ORDER)
    assert v.verdict is Verdict.VERIFIED and fired(v) == ["R4"]


UNMET_REQ = ({"requirement": 0, "line": 3, "criterion_id": "c1", "state": "weak", "min_state": "proven", "paths": ["src/**"]},)
UNMET_EV = ({"line": 5, "criterion_id": "c1", "counted_tests": 2, "non_agent_tests": 0},)

CASES = [
    ("P1 alone", dict(policy_unmet_required=UNMET_REQ), "P1", "insufficient_evidence", ["P1"]),
    ("P2 alone", dict(policy_unmet_evidence=UNMET_EV), "P2", "insufficient_evidence", ["P2"]),
    ("P1 before P2", dict(policy_unmet_required=UNMET_REQ, policy_unmet_evidence=UNMET_EV), "P1", "insufficient_evidence", ["P1", "P2"]),
    ("R1b beats P1", dict(policy_unmet_required=UNMET_REQ, ci_failed_cases=1), "R1b", "failed", ["R1b", "P1"]),
    ("R1c beats P1", dict(policy_unmet_required=UNMET_REQ, tamper=(TamperFindingInput("tf_1", "T001", "x", "high", 0.9, "a.py"),)), "R1c", "failed", ["R1c", "P1", "R3a"]),
    ("R2p beats P2", dict(policy_unmet_evidence=UNMET_EV, results_received=False), "R2p", "insufficient_evidence", ["R2p", "P2"]),
    ("R2d beats P1", dict(policy_unmet_required=UNMET_REQ, degraded=("truncated",)), "R2d", "insufficient_evidence", ["R2d", "P1"]),
    ("P1 beats R3a", dict(policy_unmet_required=UNMET_REQ, tamper=(TamperFindingInput("tf_1", "T016", "x", "medium", 0.9, "a.py"),)), "P1", "insufficient_evidence", ["P1", "R3a"]),
]


@pytest.mark.parametrize(("name", "kw", "decided", "verdict", "all_fired"), CASES, ids=[c[0] for c in CASES])
def test_policy_rule_priority(name, kw, decided, verdict, all_fired) -> None:
    v = run(policy_rules=True, **kw)
    assert v.justification["decided_by"] == decided
    assert v.verdict.value == verdict
    assert fired(v) == all_fired
    assert v.reasons[0].rule_id == decided


def test_p1_p2_have_codes_labels_and_refs() -> None:
    v = run(policy_rules=True, policy_unmet_required=UNMET_REQ, policy_unmet_evidence=UNMET_EV)
    rules = {r["id"]: r for r in v.justification["rules"]}
    assert rules["P1"]["refs"] == {"criterion_ids": ["c1"]} and rules["P2"]["refs"] == {"criterion_ids": ["c1"]}
    assert rules["P1"]["inputs"]["unmet"][0]["line"] == 3
    assert RULE_TABLE["P1"][1] == "policy_requirement_unmet" and RULE_TABLE["P2"][1] == "policy_min_evidence"
    assert "policy requirement" in v.reasons[0].detail
    assert "not agent-authored" in v.reasons[1].detail


def test_unmet_facts_are_ignored_when_the_policy_adds_no_rules() -> None:
    v = run(policy_unmet_required=UNMET_REQ)
    assert fired(v) == ["R4"]


def test_a_symbol_only_unmet_requirement_has_no_criterion_refs() -> None:
    v = run(policy_rules=True, policy_unmet_required=({"requirement": 0, "symbol_id": "s1", "path": "src/a.py", "state": "uncovered"},))
    p1 = next(r for r in v.justification["rules"] if r["id"] == "P1")
    assert p1["fired"] and p1["refs"] == {}


def test_invariants_accept_both_rule_orders_and_reject_others() -> None:
    for kw in ({}, {"policy_rules": True}):
        j = run(**kw).justification
        assert check_justification(j, criterion_ids={"c1"}, evidence_ids=set(), finding_ids=set()) == []
    j = run(policy_rules=True).justification
    j["rules"] = [r for r in j["rules"] if r["id"] != "P2"]
    problems = check_justification(j, criterion_ids={"c1"}, evidence_ids=set(), finding_ids=set())
    assert any("RULE_ORDER" in p for p in problems)


def test_policy_and_waiver_blocks_are_stored_on_the_verdict_and_in_the_tree() -> None:
    policy = {"present": True, "mode": "blocking", "provenance": [{"key": "mode", "line": 2}]}
    waivers = {"applied": [{"id": "W-1"}], "audit_digest": "sha256:x"}
    waived = ({"finding_id": "tf_1", "waived": True, "waiver": {"id": "W-1", "owner": "a", "reason": "r", "expires": "2026-12-01"}},)
    v = run(policy=policy, waivers=waivers, tamper_waived=waived)
    assert v.policy == policy and v.waivers == waivers and v.tamper_waived == waived
    assert v.justification["policy"] == policy and v.justification["waivers"] == waivers
    again = VerdictV2.from_dict(v.to_dict())
    assert again.policy == policy and again.tamper_waived == waived


def test_contract_two_verdicts_still_load() -> None:
    data = run().to_dict()
    for key in ("policy", "waivers", "tamper_waived"):
        data.pop(key)
    old = VerdictV2.from_dict(data)
    assert old.policy == {} and old.waivers == {} and old.tamper_waived == ()


@pytest.mark.parametrize(
    ("marker", "blocking"),
    [("policy_invalid", True), ("policy_unreadable", True), ("truncated", True), ("producer_failed:x", False)],
)
def test_policy_markers_block_a_verdict(marker: str, blocking: bool) -> None:
    assert is_blocking_degraded(marker) is blocking
    v = run(degraded=(marker,))
    assert (v.justification["decided_by"] == "R2d") is blocking


def test_waived_findings_never_reach_the_tamper_rules() -> None:
    # The pipeline removes waived findings before the rules; the verdict carries them separately.
    cfg = VerdictV2Config()
    criteria = [crit()]
    rules = evaluate_rules(criteria, uim(criteria), AnalysisFacts(results_received=True, behavioral_symbols=1), cfg)
    assert not any(r.fired for r in rules if r.id in ("R1c", "R3a"))
