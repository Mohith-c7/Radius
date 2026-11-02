"""Verdict rules R1 to R4 (design 3.9, VD-03).

A pure, deterministic function from already computed per-criterion results and
analysis facts to the ordered rule results. Every rule is evaluated and recorded
exactly once, in ``RULE_ORDER``; the first rule that fires decides. All numbers
come from ``VerdictV2Config``; nothing is hard-coded except rule ids and the
mapping rule -> verdict/reason code.

Imports only the standard library and ``radius_evidence.domain``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from radius_evidence.domain.config import SEVERITY_ORDER, VerdictV2Config
from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.states import UimResult

from radius_confidence.verdict_v2.domain.model import (
    POLICY_RULE_ORDER,
    RULE_ORDER,
    CriterionVerdict,
    RuleResult,
    Verdict,
)

#: Testability values that count as "behavioral" for rule R2a (the legacy
#: stored string ``testable`` still parses to the same category).
BEHAVIORAL_TESTABILITY: frozenset[str] = frozenset({"behavioral_testable", "testable"})

#: Degraded markers that block a verdict (R2d): exact or ``prefix*`` forms.
BLOCKING_DEGRADED_EXACT: frozenset[str] = frozenset(
    {"truncated", "policy_invalid", "policy_unreadable"}
)
BLOCKING_DEGRADED_PREFIXES: tuple[str, ...] = ("unsupported_language:", "snapshot_missing:")

#: rule id -> (verdict, reason code, label). Single source of the mapping.
RULE_TABLE: dict[str, tuple[Verdict, str, str]] = {
    "R1a": (Verdict.FAILED, "contradicted_criterion", "contradicted criterion"),
    "R1b": (Verdict.FAILED, "ci_failure", "failing CI case"),
    "R1c": (Verdict.FAILED, "tamper_high", "high tamper finding"),
    "R2p": (Verdict.INSUFFICIENT_EVIDENCE, "awaiting_test_results", "awaiting CI results"),
    "R2a": (
        Verdict.INSUFFICIENT_EVIDENCE,
        "intent_missing_or_untestable",
        "intent missing or untestable",
    ),
    "R2b": (Verdict.INSUFFICIENT_EVIDENCE, "unproven_intent_mass", "unproven intent mass"),
    "R2c": (Verdict.INSUFFICIENT_EVIDENCE, "low_intent_coverage", "intent coverage"),
    "R2d": (Verdict.INSUFFICIENT_EVIDENCE, "analysis_degraded", "analysis degraded"),
    "P1": (
        Verdict.INSUFFICIENT_EVIDENCE,
        "policy_requirement_unmet",
        "policy requirement unmet",
    ),
    "P2": (
        Verdict.INSUFFICIENT_EVIDENCE,
        "policy_min_evidence",
        "policy minimum evidence",
    ),
    "R3a": (Verdict.NEEDS_REVIEW, "tamper_medium", "medium tamper finding"),
    "R3b": (Verdict.NEEDS_REVIEW, "flaky_dependency", "flaky dependency"),
    "R3c": (
        Verdict.NEEDS_REVIEW,
        "weak_link_for_proven_criterion",
        "weak link for a proven criterion",
    ),
    "R4": (Verdict.VERIFIED, "all_rules_passed", "all rules passed"),
}

_FLOAT_DIGITS = 6


@dataclass(frozen=True, slots=True)
class AnalysisFacts:
    """Facts besides the criteria that the rules read (all plain data).

    ``tamper`` holds the findings that are **not** waived (waived ones are
    counted elsewhere and never reach the rules). ``behavioral_symbols`` is
    ``|B|`` of design 3.9 (changed behavioral, non-test symbols).
    """

    results_received: bool
    ci_failed_cases: int = 0
    tamper: tuple[TamperFindingInput, ...] = ()
    degraded: tuple[str, ...] = ()
    behavioral_symbols: int = 0
    flaky_test_ids: frozenset[str] = frozenset()
    #: Contract 3: True when the repository policy adds P1/P2 (then both are evaluated).
    policy_rules: bool = False
    policy_unmet_required: tuple[dict[str, Any], ...] = ()
    policy_unmet_evidence: tuple[dict[str, Any], ...] = ()


def severity_rank(label: str) -> int:
    """Rank of a severity label; unknown labels rank below ``info`` (-1)."""

    value = label.strip().lower()
    return SEVERITY_ORDER.index(value) if value in SEVERITY_ORDER else -1


def _threshold_rank(label: str) -> int:
    rank = severity_rank(label)
    if rank < 0:
        msg = f"unknown severity threshold {label!r}; expected one of {SEVERITY_ORDER}"
        raise ValueError(msg)
    return rank


def _r(value: float) -> float:
    return round(float(value), _FLOAT_DIGITS)


def is_blocking_degraded(marker: str) -> bool:
    return marker in BLOCKING_DEGRADED_EXACT or marker.startswith(BLOCKING_DEGRADED_PREFIXES)


def is_behavioral(testability: str) -> bool:
    return testability in BEHAVIORAL_TESTABILITY


def _refs(**kwargs: Sequence[str]) -> dict[str, tuple[str, ...]]:
    return {k: tuple(sorted(set(v))) for k, v in kwargs.items() if v}


def _flaky_attachments(
    criterion: CriterionVerdict, flaky_ids: frozenset[str]
) -> tuple[list[str], list[str]]:
    """Return (flaky test ids, their evidence ids) among the criterion's items."""

    tests: list[str] = []
    evidence: list[str] = []
    for item in criterion.items:
        test_id = item.path.test_id if item.path is not None else ""
        if (test_id and test_id in flaky_ids) or item.flaky_f < 1.0:
            if test_id:
                tests.append(test_id)
            evidence.append(item.evidence_id)
    return tests, evidence


def _weak_link(criterion: CriterionVerdict, link_review_min: float) -> bool:
    if Flag.LOW_LINK_CONFIDENCE in criterion.flags:
        return True
    l_cs = criterion.best_link.get("l_cs") if criterion.best_link else None
    return (
        isinstance(l_cs, (int, float))
        and not isinstance(l_cs, bool)
        and _r(l_cs) < _r(link_review_min)
    )


def evaluate_rules(
    criteria: Sequence[CriterionVerdict],
    uim: UimResult,
    facts: AnalysisFacts,
    config: VerdictV2Config,
) -> tuple[RuleResult, ...]:
    """Evaluate every rule in ``RULE_ORDER`` and return the 12 ``RuleResult``."""

    rc = config.rules
    fail_rank = _threshold_rank(rc.fail_on_tamper_at_least)
    review_rank = _threshold_rank(rc.review_on_tamper_at_least)
    results: dict[str, RuleResult] = {}

    def put(
        rule_id: str,
        fired: bool,
        inputs: dict[str, Any],
        refs: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        results[rule_id] = RuleResult(
            id=rule_id,
            label=RULE_TABLE[rule_id][2],
            fired=fired,
            inputs=inputs,
            refs=(refs or {}) if fired else {},
        )

    # R1a: any criterion contradicted.
    contradicted = sorted(c.criterion_id for c in criteria if c.state == SupportState.CONTRADICTED)
    failing_evidence = [
        r.ref
        for c in criteria
        if c.state == SupportState.CONTRADICTED
        for r in c.reasons
        if r.code == "failing_linked_test" and r.ref
    ]
    put(
        "R1a",
        bool(contradicted),
        {"contradicted": contradicted},
        _refs(criterion_ids=contradicted, evidence_ids=failing_evidence),
    )

    # R1b: any failing CI case for this head (matched to a criterion or not).
    put("R1b", facts.ci_failed_cases > 0, {"failed_cases": int(facts.ci_failed_cases)})

    # R1c: unwaived tamper finding at or above the fail threshold (severity from the engine).
    ranked = [(severity_rank(t.severity), t) for t in facts.tamper]
    high = sorted(t.finding_id for rank, t in ranked if rank >= fail_rank)
    max_sev = None
    if ranked:
        top = max(ranked, key=lambda p: p[0])
        max_sev = top[1].severity.strip().lower()
    put(
        "R1c",
        bool(high),
        {
            "threshold": rc.fail_on_tamper_at_least,
            "max_severity": max_sev,
            "finding_ids": high,
        },
        _refs(finding_ids=high),
    )

    # R2p: no CI upload yet for this head.
    put("R2p", not facts.results_received, {"results_received": bool(facts.results_received)})

    # R2a: no usable intent while behavioral code changed.
    non_excluded = [c for c in criteria if c.state != SupportState.EXCLUDED]
    testable = [c for c in non_excluded if is_behavioral(c.testability)]
    no_intent = (not non_excluded) or (not testable)
    put(
        "R2a",
        no_intent and facts.behavioral_symbols > 0,
        {
            "testable_criteria": len(testable),
            "non_excluded_criteria": len(non_excluded),
            "behavioral_symbols": int(facts.behavioral_symbols),
        },
    )

    # R2b: unproven intent mass above the limit.
    put(
        "R2b",
        _r(uim.uim) > _r(rc.uim_max),
        {
            "uim": _r(uim.uim),
            "uim_max": _r(rc.uim_max),
            "criteria": [
                {"criterion_id": c.criterion_id, "S": _r(c.S), "state": c.state.value}
                for c in non_excluded
            ],
        },
        _refs(criterion_ids=uim.unproven_criterion_ids),
    )

    # R2c: too little of the behavioral change is accounted for by a criterion.
    put(
        "R2c",
        _r(uim.intent_coverage) < _r(rc.min_intent_coverage),
        {"intent_coverage": _r(uim.intent_coverage), "min": _r(rc.min_intent_coverage)},
    )

    # R2d: degraded analysis (truncated, unsupported language, missing snapshot).
    blocking = sorted({d for d in facts.degraded if is_blocking_degraded(d)})
    put(
        "R2d",
        bool(blocking),
        {"degraded": sorted(set(facts.degraded)), "blocking": blocking},
    )

    if facts.policy_rules:
        # P1: a criterion (or changed symbol) under a required path is below the required state.
        p1_criteria = sorted(
            {str(u["criterion_id"]) for u in facts.policy_unmet_required if u.get("criterion_id")}
        )
        put(
            "P1",
            bool(facts.policy_unmet_required),
            {"unmet": [dict(u) for u in facts.policy_unmet_required]},
            _refs(criterion_ids=p1_criteria),
        )
        # P2: the policy asks for a non-agent-authored test and a criterion has none.
        p2_criteria = sorted({str(u["criterion_id"]) for u in facts.policy_unmet_evidence})
        put(
            "P2",
            bool(facts.policy_unmet_evidence),
            {"unmet": [dict(u) for u in facts.policy_unmet_evidence]},
            _refs(criterion_ids=p2_criteria),
        )

    # R3a: unwaived medium (or higher) tamper finding.
    medium = sorted(t.finding_id for rank, t in ranked if rank >= review_rank)
    put(
        "R3a",
        bool(medium),
        {"threshold": rc.review_on_tamper_at_least, "finding_ids": medium},
        _refs(finding_ids=medium),
    )

    # R3b: a flaky test behind a proven criterion.
    flaky_tests: list[str] = []
    flaky_criteria: list[str] = []
    flaky_evidence: list[str] = []
    for c in criteria:
        if c.state != SupportState.PROVEN:
            continue
        tests, evidence = _flaky_attachments(c, facts.flaky_test_ids)
        if tests or evidence or Flag.FLAKY_EVIDENCE in c.flags:
            flaky_criteria.append(c.criterion_id)
            flaky_tests.extend(tests)
            flaky_evidence.extend(evidence)
    put(
        "R3b",
        bool(flaky_criteria),
        {"flaky_tests": sorted(set(flaky_tests))},
        _refs(criterion_ids=flaky_criteria, evidence_ids=flaky_evidence),
    )

    # R3c: a proven criterion that rests on a weak criterion->symbol link.
    weak_link = sorted(
        c.criterion_id
        for c in criteria
        if c.state == SupportState.PROVEN and _weak_link(c, rc.link_review_min)
    )
    put(
        "R3c",
        bool(weak_link),
        {"link_review_min": _r(rc.link_review_min), "criterion_ids": weak_link},
        _refs(criterion_ids=weak_link),
    )

    # R4 fires only when nothing above did.
    put("R4", not any(r.fired for r in results.values()), {})

    order = POLICY_RULE_ORDER if facts.policy_rules else RULE_ORDER
    return tuple(results[rule_id] for rule_id in order)


def decide(rules: Sequence[RuleResult]) -> RuleResult:
    """The first fired rule (R4 always fires when nothing else does)."""

    for rule in rules:
        if rule.fired:
            return rule
    msg = "no rule fired; R4 must fire when no earlier rule does"
    raise ValueError(msg)


def verdict_of(rule_id: str) -> Verdict:
    return RULE_TABLE[rule_id][0]
