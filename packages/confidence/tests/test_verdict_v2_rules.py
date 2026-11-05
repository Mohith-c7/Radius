"""Verdict v2 rules R1 to R4 (VD-03): each rule alone, priority, boundaries."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import pytest
from radius_confidence.verdict_v2.application.service import (
    build_criterion_verdict,
    compute_verdict_v2,
)
from radius_confidence.verdict_v2.domain.model import (
    RULE_ORDER,
    CriterionVerdict,
    Verdict,
    VerdictV2,
)
from radius_confidence.verdict_v2.domain.rules import (
    AnalysisFacts,
    decide,
    evaluate_rules,
    is_blocking_degraded,
    severity_rank,
)
from radius_confidence.verdict_v2.domain.tree import check_justification, thresholds_of
from radius_evidence.domain.config import RuleConfig, SupportConfig, VerdictV2Config
from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import CriterionInput, TamperFindingInput
from radius_evidence.domain.model import Reason
from radius_evidence.domain.quality import ChainRef, EvidenceQuality
from radius_evidence.domain.states import CriterionStateResult, UimResult
from radius_evidence.domain.support import SupportResult

HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
TAU = 0.5


def item(
    eid: str = "ev_1",
    test_id: str = "tests/t.py::test_a",
    *,
    flaky_f: float = 1.0,
    status: str = "counted",
    l_cs: float = 1.0,
    contribution: float | None = 0.4,
    cid: str = "c1",
) -> EvidenceQuality:
    return EvidenceQuality(
        evidence_id=eid,
        criterion_id=cid,
        a_static=1.0,
        d_eff=0.6,
        cap_static=0.6,
        i=0.8,
        f=1.0,
        flaky_f=flaky_f,
        tamper_penalty=0.0,
        q=0.48,
        l_cs=l_cs,
        l_st=0.9,
        r_ct=1.0,
        l=0.9 * l_cs,
        term=0.432,
        status=status,
        contribution=contribution,
        path=ChainRef(symbol_id="sym:f", test_id=test_id, l_cs=l_cs, l_st=0.9, r_ct=1.0),
    )


def crit(
    cid: str = "c1",
    state: SupportState = SupportState.PROVEN,
    s: float = 0.6,
    *,
    testability: str = "behavioral_testable",
    flags: tuple[Flag, ...] = (),
    items: tuple[EvidenceQuality, ...] | None = None,
    reasons: tuple[Reason, ...] = (),
    weight: float = 1.0,
    l_cs: float = 1.0,
) -> CriterionVerdict:
    rows = (item(f"ev_{cid}", cid=cid, l_cs=l_cs),) if items is None else items
    best = {"symbol_id": "sym:f", "l_cs": l_cs, "l_st": 0.9, "r_ct": 1.0} if rows else {}
    return CriterionVerdict(
        criterion_id=cid,
        text=f"criterion {cid}",
        weight=weight,
        testability=testability,
        lifecycle="confirmed",
        state=state,
        S=s,
        S_raw=s,
        reasons=reasons,
        flags=flags,
        items=rows,
        best_link=best,
    )


def uim_of(criteria: list[CriterionVerdict], coverage: float = 1.0) -> UimResult:
    live = [c for c in criteria if c.state != SupportState.EXCLUDED]
    den = sum(c.weight for c in live)
    unproven = [c for c in live if c.S < TAU or c.state == SupportState.CONTRADICTED]
    num = sum(c.weight for c in unproven)
    return UimResult(
        uim=0.0 if den == 0 else num / den,
        numerator=num,
        denominator=den,
        intent_coverage=coverage,
        unproven_criterion_ids=tuple(c.criterion_id for c in unproven),
        excluded_criterion_ids=tuple(
            c.criterion_id for c in criteria if c.state == SupportState.EXCLUDED
        ),
    )


def tamper(fid: str = "tf_1", severity: str = "high", rule: str = "T001") -> TamperFindingInput:
    return TamperFindingInput(
        finding_id=fid, rule_id=rule, check="x", severity=severity, confidence=0.9, path="a.py"
    )


def facts(**kw: Any) -> AnalysisFacts:
    base: dict[str, Any] = {"results_received": True, "behavioral_symbols": 1}
    base.update(kw)
    return AnalysisFacts(**base)


def run(
    criteria: list[CriterionVerdict],
    *,
    coverage: float = 1.0,
    uim: UimResult | None = None,
    config: VerdictV2Config | None = None,
    **kw: Any,
) -> VerdictV2:
    return compute_verdict_v2(
        analysis_id="an-1",
        head_sha=HEAD,
        revision=1,
        criteria=criteria,
        uim=uim or uim_of(criteria, coverage),
        facts=facts(**kw),
        config=config,
    )


def fired(v: VerdictV2) -> list[str]:
    return [r["id"] for r in v.justification["rules"] if r["fired"]]


PROVEN = lambda cid="c1": crit(cid)  # noqa: E731
WEAK = lambda cid="c2": crit(cid, SupportState.WEAK, 0.3)  # noqa: E731
UNEV = lambda cid="c3": crit(cid, SupportState.UNEVIDENCED, 0.0, items=())  # noqa: E731
CONTRA = lambda cid="c4": crit(  # noqa: E731
    cid,
    SupportState.CONTRADICTED,
    0.0,
    reasons=(Reason("failing_linked_test", "a failing test", "ev_fail"),),
    items=(item("ev_fail", cid=cid, status="gated:failed"),),
)


# --------------------------------------------------------------------------- each rule alone

ALONE: list[tuple[str, dict[str, Any], list[CriterionVerdict], Verdict, str]] = [
    ("R4 clean", {}, [PROVEN()], Verdict.VERIFIED, "R4"),
    ("R1a contradicted", {}, [PROVEN(), CONTRA()], Verdict.FAILED, "R1a"),
    ("R1b ci failure", {"ci_failed_cases": 1}, [PROVEN()], Verdict.FAILED, "R1b"),
    ("R1b many failures", {"ci_failed_cases": 7}, [PROVEN()], Verdict.FAILED, "R1b"),
    ("R1c high tamper", {"tamper": (tamper(),)}, [PROVEN()], Verdict.FAILED, "R1c"),
    ("R1c critical tamper", {"tamper": (tamper(severity="critical"),)}, [PROVEN()], Verdict.FAILED, "R1c"),
    ("R2p pending", {"results_received": False}, [PROVEN()], Verdict.INSUFFICIENT_EVIDENCE, "R2p"),
    ("R2a no criteria", {"behavioral_symbols": 3}, [], Verdict.INSUFFICIENT_EVIDENCE, "R2a"),
    (
        "R2a only vague",
        {},
        [crit("c1", SupportState.EXCLUDED, 0.0, testability="subjective_or_vague", items=())],
        Verdict.INSUFFICIENT_EVIDENCE,
        "R2a",
    ),
    (
        "R2a only non functional",
        {},
        [crit("c1", SupportState.UNEVIDENCED, 0.0, testability="non_functional_measurable", items=())],
        Verdict.INSUFFICIENT_EVIDENCE,
        "R2a",
    ),
    ("R2b unproven mass", {}, [PROVEN(), UNEV()], Verdict.INSUFFICIENT_EVIDENCE, "R2b"),
    ("R2b weak only", {}, [WEAK()], Verdict.INSUFFICIENT_EVIDENCE, "R2b"),
    ("R2c low coverage", {"coverage": 0.3}, [PROVEN()], Verdict.INSUFFICIENT_EVIDENCE, "R2c"),
    ("R2d truncated", {"degraded": ("truncated",)}, [PROVEN()], Verdict.INSUFFICIENT_EVIDENCE, "R2d"),
    (
        "R2d unsupported language",
        {"degraded": ("unsupported_language:ts",)},
        [PROVEN()],
        Verdict.INSUFFICIENT_EVIDENCE,
        "R2d",
    ),
    (
        "R2d snapshot missing",
        {"degraded": ("snapshot_missing:base",)},
        [PROVEN()],
        Verdict.INSUFFICIENT_EVIDENCE,
        "R2d",
    ),
    ("R3a medium tamper", {"tamper": (tamper(severity="medium"),)}, [PROVEN()], Verdict.NEEDS_REVIEW, "R3a"),
    (
        "R3b flaky by id",
        {"flaky_test_ids": frozenset({"tests/t.py::test_a"})},
        [PROVEN()],
        Verdict.NEEDS_REVIEW,
        "R3b",
    ),
    (
        "R3b flaky by flaky_f",
        {},
        [crit("c1", items=(item("ev_x", flaky_f=0.7),))],
        Verdict.NEEDS_REVIEW,
        "R3b",
    ),
    (
        "R3b flaky by flag",
        {},
        [crit("c1", flags=(Flag.FLAKY_EVIDENCE,))],
        Verdict.NEEDS_REVIEW,
        "R3b",
    ),
    ("R3c weak link", {}, [crit("c1", l_cs=0.3)], Verdict.NEEDS_REVIEW, "R3c"),
    (
        "R3c low link flag",
        {},
        [crit("c1", flags=(Flag.LOW_LINK_CONFIDENCE,))],
        Verdict.NEEDS_REVIEW,
        "R3c",
    ),
]


@pytest.mark.parametrize(("name", "kw", "criteria", "verdict", "rule"), ALONE, ids=[a[0] for a in ALONE])
def test_each_rule_fires_alone(
    name: str, kw: dict[str, Any], criteria: list[CriterionVerdict], verdict: Verdict, rule: str
) -> None:
    v = run(criteria, **kw)
    assert v.verdict == verdict
    assert v.justification["decided_by"] == rule
    # The deciding rule is the first fired; later rules may also fire (e.g. a high
    # tamper finding is also a medium one, a contradicted criterion is unproven).
    assert fired(v)[0] == rule
    assert v.reasons[0].ref == rule
    if rule == "R4":
        assert fired(v) == ["R4"]
    assert len(v.justification["rules"]) == len(RULE_ORDER)


# ------------------------------------------------------------------ priority / combinations

COMBOS: list[tuple[str, dict[str, Any], list[CriterionVerdict], str, list[str]]] = [
    ("R1a beats R1b", {"ci_failed_cases": 2}, [CONTRA()], "R1a", ["R1a", "R1b", "R2b"]),
    ("R1b beats R1c", {"ci_failed_cases": 1, "tamper": (tamper(),)}, [PROVEN()], "R1b", ["R1b", "R1c", "R3a"]),
    (
        "R1c beats R2p",
        {"tamper": (tamper(),), "results_received": False},
        [PROVEN()],
        "R1c",
        ["R1c", "R2p", "R3a"],
    ),
    (
        "R1b beats R2p",
        {"ci_failed_cases": 1, "results_received": False},
        [PROVEN()],
        "R1b",
        ["R1b", "R2p"],
    ),
    ("R2p beats R2b", {"results_received": False}, [UNEV()], "R2p", ["R2p", "R2b"]),
    ("R2a beats R2b", {"behavioral_symbols": 2}, [], "R2a", ["R2a"]),
    ("R2b beats R2c", {"coverage": 0.1}, [UNEV()], "R2b", ["R2b", "R2c"]),
    ("R2c beats R2d", {"coverage": 0.1, "degraded": ("truncated",)}, [PROVEN()], "R2c", ["R2c", "R2d"]),
    (
        "R2d beats R3a",
        {"degraded": ("truncated",), "tamper": (tamper(severity="medium"),)},
        [PROVEN()],
        "R2d",
        ["R2d", "R3a"],
    ),
    (
        "R3a beats R3b",
        {"tamper": (tamper(severity="medium"),), "flaky_test_ids": frozenset({"tests/t.py::test_a"})},
        [PROVEN()],
        "R3a",
        ["R3a", "R3b"],
    ),
    (
        "R3b beats R3c",
        {"flaky_test_ids": frozenset({"tests/t.py::test_a"})},
        [crit("c1", l_cs=0.3)],
        "R3b",
        ["R3b", "R3c"],
    ),
    (
        "all three R1 together",
        {"ci_failed_cases": 1, "tamper": (tamper(),)},
        [CONTRA()],
        "R1a",
        ["R1a", "R1b", "R1c", "R2b", "R3a"],
    ),
    (
        "fixture 05 style: auto R2b and R2c",
        {"coverage": 0.33},
        [crit("c1", SupportState.WEAK, 0.336), UNEV("c2")],
        "R2b",
        ["R2b", "R2c"],
    ),
]


@pytest.mark.parametrize(("name", "kw", "criteria", "decided", "all_fired"), COMBOS, ids=[c[0] for c in COMBOS])
def test_priority_and_combinations(
    name: str, kw: dict[str, Any], criteria: list[CriterionVerdict], decided: str, all_fired: list[str]
) -> None:
    v = run(criteria, **kw)
    assert v.justification["decided_by"] == decided
    assert fired(v) == all_fired
    # Every fired rule is a reason, deciding rule first.
    assert [r.ref for r in v.reasons] == all_fired
    assert v.verdict == Verdict(v.justification["verdict"])


# -------------------------------------------------------------------------- boundaries

def test_uim_equal_to_limit_does_not_fire() -> None:
    # 1 unproven of 5 equal weights gives exactly 0.20 == uim_max.
    criteria = [crit(f"c{i}") for i in range(4)] + [UNEV("c9")]
    v = run(criteria)
    assert v.uim == pytest.approx(0.2)
    assert v.verdict == Verdict.VERIFIED


def test_uim_just_above_limit_fires() -> None:
    criteria = [crit(f"c{i}") for i in range(3)] + [UNEV("c9")]
    v = run(criteria)
    assert v.uim == pytest.approx(0.25)
    assert v.justification["decided_by"] == "R2b"


@pytest.mark.parametrize(
    ("uim_value", "expected"),
    [(0.0, False), (0.199999, False), (0.2, False), (0.2000001, False), (0.200001, True), (0.5, True), (1.0, True)],
)
def test_uim_threshold_boundary_values(uim_value: float, expected: bool) -> None:
    criteria = [PROVEN()]
    u = replace(uim_of(criteria), uim=uim_value)
    v = run(criteria, uim=u)
    assert ("R2b" in fired(v)) is expected


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [(1.0, False), (0.5, False), (0.500001, False), (0.4999999, False), (0.499999, True), (0.0, True)],
)
def test_intent_coverage_boundary_values(coverage: float, expected: bool) -> None:
    v = run([PROVEN()], coverage=coverage)
    assert ("R2c" in fired(v)) is expected


@pytest.mark.parametrize(
    ("severity", "fails", "reviews"),
    [
        ("info", False, False),
        ("low", False, False),
        ("medium", False, True),
        ("high", True, True),
        ("critical", True, True),
        ("HIGH", True, True),
        ("unknown", False, False),
    ],
)
def test_tamper_severity_thresholds(severity: str, fails: bool, reviews: bool) -> None:
    v = run([PROVEN()], tamper=(tamper(severity=severity),))
    assert ("R1c" in fired(v)) is fails
    assert ("R3a" in fired(v)) is reviews


def test_tamper_thresholds_come_from_config() -> None:
    cfg = VerdictV2Config(rules=RuleConfig(fail_on_tamper_at_least="medium", review_on_tamper_at_least="low"))
    v = run([PROVEN()], tamper=(tamper(severity="medium"),), config=cfg)
    assert v.justification["decided_by"] == "R1c"
    assert v.justification["thresholds"]["fail_on_tamper_at_least"] == "medium"
    v = run([PROVEN()], tamper=(tamper(severity="low"),), config=cfg)
    assert v.justification["decided_by"] == "R3a"


def test_uim_max_and_coverage_come_from_config() -> None:
    criteria = [PROVEN(), PROVEN("c2"), UNEV("c3")]
    assert run(criteria).justification["decided_by"] == "R2b"
    lax = VerdictV2Config(rules=RuleConfig(uim_max=0.5, min_intent_coverage=0.9))
    assert run(criteria, config=lax).verdict == Verdict.VERIFIED
    assert run(criteria, coverage=0.8, config=lax).justification["decided_by"] == "R2c"


def test_link_review_min_boundary() -> None:
    cfg = VerdictV2Config(rules=RuleConfig(link_review_min=0.5))
    assert run([crit("c1", l_cs=0.5)], config=cfg).verdict == Verdict.VERIFIED
    assert run([crit("c1", l_cs=0.49)], config=cfg).justification["decided_by"] == "R3c"


def test_unknown_severity_threshold_is_a_config_error() -> None:
    cfg = VerdictV2Config(rules=RuleConfig(fail_on_tamper_at_least="severe"))
    with pytest.raises(ValueError, match="unknown severity threshold"):
        run([PROVEN()], config=cfg)


@pytest.mark.parametrize(
    ("marker", "blocking"),
    [
        ("truncated", True),
        ("unsupported_language:ts", True),
        ("unsupported_language:", True),
        ("snapshot_missing:head", True),
        ("note:renamed", False),
        ("truncated_extra", False),
        ("", False),
    ],
)
def test_degraded_markers(marker: str, blocking: bool) -> None:
    assert is_blocking_degraded(marker) is blocking


def test_non_blocking_degraded_marker_is_recorded_but_does_not_fire() -> None:
    v = run([PROVEN()], degraded=("note:renamed",))
    r2d = next(r for r in v.justification["rules"] if r["id"] == "R2d")
    assert r2d["fired"] is False
    assert r2d["inputs"] == {"degraded": ["note:renamed"], "blocking": []}


# ---------------------------------------------------------------------- R2a specifics

def test_r2a_needs_a_behavioral_change() -> None:
    # No criteria and no behavioral symbols: R2a does not fire; R2e (DEC-031) decides.
    v = run([], behavioral_symbols=0)
    assert "R2a" not in fired(v)
    assert v.verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert v.uim == 0.0


def test_r2e_zero_criteria_is_never_verified() -> None:
    v = run([], behavioral_symbols=0)
    assert v.justification["decided_by"] == "R2e"
    assert [r.code for r in v.reasons] == ["no_intent_criteria"]
    assert "no intent criteria were extracted; add a spec or confirm criteria" in v.reasons[0].detail
    assert v.pending is False


def test_r2e_only_excluded_criteria_counts_as_none() -> None:
    v = run([crit("c1", SupportState.EXCLUDED, 0.0, testability="subjective_vague", items=())], behavioral_symbols=0)
    assert v.justification["decided_by"] == "R2e"


def test_r2e_inert_changes_are_not_applicable() -> None:
    v = run([], behavioral_symbols=0, inert_changes_only=True)
    assert v.justification["decided_by"] == "R2e"
    assert v.verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert [r.code for r in v.reasons] == ["not_applicable"]
    assert "not applicable" in v.reasons[0].detail


def test_r2e_does_not_hide_review_level_tamper() -> None:
    v = run([], behavioral_symbols=0, inert_changes_only=True, tamper=(tamper(severity="medium"),))
    assert v.justification["decided_by"] == "R3a"
    assert "R2e" not in fired(v)


def test_r2e_low_tamper_does_not_prevent_it() -> None:
    v = run([], behavioral_symbols=0, tamper=(tamper(severity="low"),))
    assert v.justification["decided_by"] == "R2e"


def test_r2e_silent_when_a_real_criterion_exists() -> None:
    assert "R2e" not in fired(run([PROVEN()], behavioral_symbols=0))


def test_r2a_beats_r2e_when_behavioral_code_changed() -> None:
    v = run([], behavioral_symbols=3)
    assert v.justification["decided_by"] == "R2a" and "R2e" not in fired(v)


@pytest.mark.parametrize(
    ("path", "inert"),
    [
        ("README.md", True), ("docs/guide.md", True), ("LICENSE", True), ("docs/img/a.png", True),
        (".gitignore", True), ("changelog.d/123.md", True),
        (".github/workflows/ci.yml", False), ("pyproject.toml", False), ("uv.lock", True),
        ("requirements.txt", False), ("Dockerfile", False), ("src/app.py", False),
        ("tests/test_a.py", False), ("docs/conf.py", False), (".github/README.md", False),
        # B-12: names that only look inert
        ("src/changelog.py", False), ("tools/changelog_gen.sh", False), ("licence_check.py", False),
        ("docs/build.mjs", False), ("docs/gen.go", False), ("doc/Makefile", False),
        ("CMakeLists.txt", False), ("requirements-dev.txt", False), ("constraints-dev.txt", False),
        ("requirements/prod.txt", False), ("docs/deploy.ps1", False), ("docs/Dockerfile", False),
        ("src/LICENSE.py", False), ("src/app.svg", False),
        ("CHANGELOG", True), ("changelog.d/.gitkeep", True), ("package-lock.json", True),
    ],
)
def test_is_inert_path(path: str, inert: bool) -> None:
    from radius_confidence.verdict_v2.domain.rules import is_inert_path

    assert is_inert_path(path) is inert


def test_b02_r2e_is_not_applicable_only_without_blocking_degraded_markers() -> None:
    v = run([], behavioral_symbols=0, inert_changes_only=True, degraded=("unanalyzed_files:2",))
    r2e = next(r for r in v.justification["rules"] if r["id"] == "R2e")
    assert r2e["fired"] is True and r2e["inputs"]["not_applicable"] is False
    assert "R2d" in fired(v)
    assert v.verdict == Verdict.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("marker", ["unanalyzed_files:1", "tamper_unanalyzed:files=3", "tamper_unanalyzed:context_error"])
def test_b02_b03_markers_block_verified(marker: str) -> None:
    assert run([PROVEN()]).verdict == Verdict.VERIFIED
    v = run([PROVEN()], degraded=(marker,))
    assert v.verdict == Verdict.INSUFFICIENT_EVIDENCE and "R2d" in fired(v)


def test_r2a_legacy_testability_string_counts_as_behavioral() -> None:
    v = run([crit("c1", testability="testable")])
    assert "R2a" not in fired(v)


def test_r2a_structural_only_does_not_count_as_behavioral() -> None:
    v = run([crit("c1", testability="structural_checkable")])
    assert v.justification["decided_by"] == "R2a"


def test_r2a_inputs_record_counts() -> None:
    v = run(
        [
            crit("c1", SupportState.EXCLUDED, 0.0, testability="untestable_external", items=()),
            crit("c2", SupportState.UNEVIDENCED, 0.0, testability="structural_checkable", items=()),
        ]
    )
    r2a = next(r for r in v.justification["rules"] if r["id"] == "R2a")
    assert r2a["inputs"] == {"testable_criteria": 0, "non_excluded_criteria": 1, "behavioral_symbols": 1}


# ----------------------------------------------------------------------- pending / flags

def test_pending_only_when_r2p_decides() -> None:
    assert run([PROVEN()], results_received=False).pending is True
    assert run([PROVEN()]).pending is False
    assert run([PROVEN()], results_received=False, ci_failed_cases=1).pending is False
    assert run([PROVEN()], results_received=False, tamper=(tamper(),)).pending is False


def test_pending_verdict_is_insufficient_evidence_with_reason() -> None:
    v = run([UNEV(), WEAK()], results_received=False)
    assert v.verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert v.reasons[0].code == "awaiting_test_results"
    assert v.justification["decided_by"] == "R2p"


def test_r3b_only_considers_proven_criteria() -> None:
    weak_flaky = crit("c2", SupportState.WEAK, 0.45, items=(item("ev_w", flaky_f=0.5, cid="c2"),))
    v = run([PROVEN(), weak_flaky, crit("c3")], uim=replace(uim_of([PROVEN()]), uim=0.0))
    assert "R3b" not in fired(v)


def test_r3b_refs_point_to_existing_evidence() -> None:
    v = run([crit("c1", items=(item("ev_flaky", flaky_f=0.6),))])
    r3b = next(r for r in v.justification["rules"] if r["id"] == "R3b")
    assert r3b["refs"] == {"criterion_ids": ["c1"], "evidence_ids": ["ev_flaky"]}
    assert r3b["inputs"] == {"flaky_tests": ["tests/t.py::test_a"]}


def test_r1a_refs_use_failing_evidence_ids() -> None:
    v = run([CONTRA()])
    r1a = v.justification["rules"][0]
    assert r1a["refs"] == {"criterion_ids": ["c4"], "evidence_ids": ["ev_fail"]}


def test_not_fired_rules_have_no_refs() -> None:
    v = run([PROVEN(), UNEV()])
    for rule in v.justification["rules"]:
        if not rule["fired"]:
            assert rule["refs"] == {}


def test_r1c_inputs_report_max_severity_over_all_findings() -> None:
    v = run([PROVEN()], tamper=(tamper("tf_a", "low"), tamper("tf_b", "critical"), tamper("tf_c", "high")))
    r1c = next(r for r in v.justification["rules"] if r["id"] == "R1c")
    assert r1c["inputs"] == {"threshold": "high", "max_severity": "critical", "finding_ids": ["tf_b", "tf_c"]}
    assert r1c["refs"] == {"finding_ids": ["tf_b", "tf_c"]}
    assert v.tamper[0].finding_id == "tf_a"


def test_r2b_lists_only_non_excluded_criteria() -> None:
    ex = crit("c5", SupportState.EXCLUDED, 0.0, testability="subjective_or_vague", items=())
    v = run([PROVEN(), UNEV(), ex])
    r2b = next(r for r in v.justification["rules"] if r["id"] == "R2b")
    assert [c["criterion_id"] for c in r2b["inputs"]["criteria"]] == ["c1", "c3"]
    assert r2b["refs"]["criterion_ids"] == ["c3"]


# ---------------------------------------------------------------- determinism / contract

def test_rule_results_are_in_rule_order_and_unique() -> None:
    rules = evaluate_rules([PROVEN()], uim_of([PROVEN()]), facts(), VerdictV2Config())
    assert tuple(r.id for r in rules) == RULE_ORDER
    assert decide(rules).id == "R4"


def test_decide_without_fired_rule_is_an_error() -> None:
    rules = evaluate_rules([PROVEN()], uim_of([PROVEN()]), facts(), VerdictV2Config())
    silent = tuple(replace(r, fired=False) for r in rules)
    with pytest.raises(ValueError, match="no rule fired"):
        decide(silent)


def test_compute_is_deterministic_and_order_independent_for_facts() -> None:
    a = run([PROVEN(), UNEV()], tamper=(tamper("tf_1", "medium"), tamper("tf_2", "medium")))
    b = run([PROVEN(), UNEV()], tamper=(tamper("tf_2", "medium"), tamper("tf_1", "medium")))
    assert a.justification["rules"] == b.justification["rules"]
    assert run([PROVEN(), UNEV()]).to_json() == run([PROVEN(), UNEV()]).to_json()


def test_inputs_digest_changes_with_inputs_and_can_be_supplied() -> None:
    a = run([PROVEN()])
    b = run([PROVEN()], ci_failed_cases=1)
    assert a.inputs_digest != b.inputs_digest
    assert a.inputs_digest.startswith("sha256:")
    given = compute_verdict_v2(
        analysis_id="a",
        head_sha=HEAD,
        revision=3,
        criteria=[PROVEN()],
        uim=uim_of([PROVEN()]),
        facts=facts(),
        inputs_digest="sha256:given",
    )
    assert given.inputs_digest == "sha256:given"
    assert given.justification["inputs_digest"] == "sha256:given"
    assert given.revision == 3


def test_config_digest_and_profile_are_stamped() -> None:
    v = run([PROVEN()])
    cfg = VerdictV2Config()
    assert v.config_digest == "sha256:" + cfg.digest()
    assert v.justification["config_digest"] == v.config_digest
    assert v.profile == "alpha-static"
    assert v.algo_version == "verdict-v2-alpha-1"
    assert v.evidence_basis == "static_only"


def test_thresholds_in_tree_follow_config() -> None:
    cfg = VerdictV2Config(support=SupportConfig(tau_support=0.6), rules=RuleConfig(uim_max=0.3))
    v = run([PROVEN()], config=cfg)
    assert v.justification["thresholds"]["tau_support"] == 0.6
    assert v.justification["thresholds"]["uim_max"] == 0.3


def test_verdict_round_trips_through_json() -> None:
    v = run([PROVEN(), UNEV()], tamper=(tamper("tf_1", "medium"),))
    assert VerdictV2.from_json(v.to_json()) == v


def test_uim_numbers_are_copied() -> None:
    v = run([PROVEN(), UNEV(), WEAK()])
    assert (v.uim_numerator, v.uim_denominator) == (2.0, 3.0)
    assert v.intent_coverage == 1.0


def test_unlinked_symbols_are_passed_through() -> None:
    v = compute_verdict_v2(
        analysis_id="a",
        head_sha=HEAD,
        revision=1,
        criteria=[PROVEN()],
        uim=uim_of([PROVEN()]),
        facts=facts(),
        unlinked_symbols=("src/a.py::f",),
    )
    assert v.unlinked_symbols == ("src/a.py::f",)


@pytest.mark.parametrize(
    ("label", "rank"),
    [("info", 0), ("low", 1), ("medium", 2), ("high", 3), ("critical", 4), (" High ", 3), ("nope", -1)],
)
def test_severity_rank(label: str, rank: int) -> None:
    assert severity_rank(label) == rank


# ------------------------------------------------------------------ build_criterion_verdict

def _inputs(cid: str = "c1") -> tuple[CriterionInput, SupportResult, CriterionStateResult]:
    ci = CriterionInput(cid, "text", 1.0, "behavioral_testable", "confirmed")
    sr = SupportResult(
        criterion_id=cid,
        S=0.6,
        S_raw=0.6,
        items=(item("ev_b", cid=cid, contribution=0.2), item("ev_a", cid=cid, contribution=0.4)),
        n_counted=2,
        has_strong_item=True,
    )
    st = CriterionStateResult(cid, SupportState.PROVEN, flags=(Flag.STATIC_ONLY,))
    return ci, sr, st


def test_build_criterion_verdict_joins_inputs_and_picks_best_link() -> None:
    cv = build_criterion_verdict(*_inputs())
    assert (cv.criterion_id, cv.state, cv.S, cv.flags) == ("c1", SupportState.PROVEN, 0.6, (Flag.STATIC_ONLY,))
    assert cv.best_link == {"symbol_id": "sym:f", "l_cs": 1.0, "l_st": 0.9, "r_ct": 1.0}
    assert len(cv.items) == 2


def test_build_criterion_verdict_rejects_mismatched_ids() -> None:
    ci, sr, st = _inputs()
    with pytest.raises(ValueError, match="different criteria"):
        build_criterion_verdict(ci, sr, replace(st, criterion_id="other"))


def test_build_criterion_verdict_without_items_has_empty_best_link() -> None:
    ci, sr, st = _inputs()
    cv = build_criterion_verdict(ci, replace(sr, items=(), n_counted=0), st)
    assert cv.best_link == {}


def test_best_link_falls_back_to_strongest_uncounted_path() -> None:
    ci, sr, st = _inputs()
    gated = (
        item("ev_g1", cid="c1", status="gated:skipped", l_cs=0.5),
        item("ev_g2", cid="c1", status="gated:skipped", l_cs=1.0),
    )
    cv = build_criterion_verdict(ci, replace(sr, items=gated, n_counted=0), st)
    assert cv.best_link["l_cs"] == 1.0


# ------------------------------------------------------------ justification tree

def _tree() -> dict[str, Any]:
    return run([PROVEN(), UNEV()], tamper=(tamper("tf_1", "medium"),)).justification


def _check(j: dict[str, Any]) -> list[str]:
    return check_justification(
        j, criterion_ids={"c1", "c3"}, evidence_ids={"ev_c1"}, finding_ids={"tf_1"}
    )


def test_valid_tree_has_no_violations() -> None:
    assert _check(_tree()) == []


def test_tree_lists_every_rule_once_in_order() -> None:
    assert [r["id"] for r in _tree()["rules"]] == list(RULE_ORDER)


MUTATIONS = {
    "wrong schema": lambda j: j.update(schema="other"),
    "wrong decided_by": lambda j: j.update(decided_by="R4"),
    "wrong verdict": lambda j: j.update(verdict="verified"),
    "dropped rule": lambda j: j["rules"].pop(3),
    "swapped rules": lambda j: j["rules"].reverse(),
    "unknown criterion ref": lambda j: j["rules"][6]["refs"]["criterion_ids"].append("ghost"),
    "unknown finding ref": lambda j: j["rules"][9]["refs"]["finding_ids"].append("ghost"),
    "unknown evidence ref": lambda j: j["rules"][6]["refs"].update(evidence_ids=["ghost"]),
    "unknown ref key": lambda j: j["rules"][6]["refs"].update(widgets=["x"]),
    "refs on unfired rule": lambda j: j["rules"][0].update(refs={"criterion_ids": ["c1"]}),
    "nothing fired": lambda j: [r.update(fired=False) for r in j["rules"]],
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_broken_trees_are_detected(name: str) -> None:
    tree = copy.deepcopy(_tree())
    MUTATIONS[name](tree)
    assert _check(tree), name


def test_missing_rules_key() -> None:
    assert "rules: missing" in _check({"schema": "verdict-v2-justification-1"})


def test_thresholds_are_read_from_config() -> None:
    cfg = VerdictV2Config(rules=RuleConfig(uim_max=0.35, min_intent_coverage=0.7))
    t = thresholds_of(cfg)
    assert t["uim_max"] == 0.35
    assert t["min_intent_coverage"] == 0.7
    assert set(t) == {
        "tau_support",
        "uim_max",
        "min_intent_coverage",
        "fail_on_tamper_at_least",
        "review_on_tamper_at_least",
    }


def test_service_refuses_a_tree_that_violates_its_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    import radius_confidence.verdict_v2.application.service as service

    monkeypatch.setattr(service, "check_justification", lambda *a, **k: ["boom"])
    with pytest.raises(ValueError, match="invariants violated: boom"):
        run([PROVEN()])
