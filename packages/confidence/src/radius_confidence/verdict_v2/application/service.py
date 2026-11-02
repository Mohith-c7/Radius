"""Compute a ``VerdictV2`` from per-criterion results and analysis facts (VD-03).

Pure and deterministic: no clock, no I/O. The caller (the worker's Stage B)
supplies the per-criterion ``CriterionVerdict`` rows (assembled with
``build_criterion_verdict`` from VD-01 ``SupportResult`` and VD-02
``CriterionStateResult``), the ``UimResult`` and the ``AnalysisFacts``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.inputs import CriterionInput
from radius_evidence.domain.model import Reason
from radius_evidence.domain.quality import EvidenceQuality
from radius_evidence.domain.serialization import canonical_json, sha256_hex
from radius_evidence.domain.states import CriterionStateResult, UimResult
from radius_evidence.domain.support import SupportResult
from radius_evidence.domain.versions import ALGO_VERSION

from radius_confidence.verdict_v2.domain.model import (
    CriterionVerdict,
    RuleResult,
    VerdictV2,
)
from radius_confidence.verdict_v2.domain.rules import (
    RULE_TABLE,
    AnalysisFacts,
    decide,
    evaluate_rules,
)
from radius_confidence.verdict_v2.domain.tree import (
    build_justification,
    check_justification,
)


def _best_link(items: Sequence[EvidenceQuality]) -> dict[str, object]:
    """Link of the strongest counted item (ties: evidence id); else best ``l``."""

    counted = [i for i in items if i.status == "counted" and i.path is not None]
    pool = counted or [i for i in items if i.path is not None]
    if not pool:
        return {}
    def weight(item: EvidenceQuality) -> float:
        if not counted:
            return item.l
        return item.contribution if item.contribution is not None else item.term

    best = sorted(pool, key=lambda i: (-weight(i), i.evidence_id))[0]
    assert best.path is not None
    return {
        "symbol_id": best.path.symbol_id,
        "l_cs": best.l_cs,
        "l_st": best.l_st,
        "r_ct": best.r_ct,
    }


def build_criterion_verdict(
    criterion: CriterionInput,
    support: SupportResult,
    state: CriterionStateResult,
) -> CriterionVerdict:
    """Join intent, support and state of one criterion (ids must agree)."""

    if not (criterion.criterion_id == support.criterion_id == state.criterion_id):
        msg = "criterion, support and state refer to different criteria"
        raise ValueError(msg)
    return CriterionVerdict(
        criterion_id=criterion.criterion_id,
        text=criterion.text,
        weight=criterion.weight,
        testability=criterion.testability,
        lifecycle=criterion.lifecycle,
        state=state.state,
        S=support.S,
        S_raw=support.S_raw,
        reasons=state.reasons,
        flags=state.flags,
        items=support.items,
        best_link=_best_link(support.items),
        provenance=criterion.provenance,
        hints=tuple(
            sorted(
                [
                    {"kind": "paths", "value": v, "provenance": criterion.hints_provenance}
                    for v in criterion.hints_paths
                ]
                + [
                    {"kind": "tests", "value": v, "provenance": criterion.hints_provenance}
                    for v in criterion.hints_tests
                ],
                key=lambda h: (h["kind"], h["value"]),
            )
        ),
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _detail(rule: RuleResult) -> str:
    i = rule.inputs
    rid = rule.id
    if rid == "R1a":
        return "criteria contradicted by a failing linked test: " + ", ".join(i["contradicted"])
    if rid == "R1b":
        return f"{i['failed_cases']} failing CI case(s) reported for this commit"
    if rid == "R1c":
        return (
            f"{len(i['finding_ids'])} tamper finding(s) at severity {i['threshold']} or above "
            f"(highest: {i['max_severity']})"
        )
    if rid == "R2p":
        return "no CI test results received yet for this commit"
    if rid == "R2a":
        return (
            "no behavioral_testable criterion while behavioral code changed "
            f"({i['behavioral_symbols']} changed behavioral symbol(s))"
        )
    if rid == "R2b":
        return f"unsupported intent mass {_fmt(i['uim'])} exceeds {_fmt(i['uim_max'])}"
    if rid == "R2c":
        return f"intent coverage {_fmt(i['intent_coverage'])} is below {_fmt(i['min'])}"
    if rid == "R2d":
        return "analysis degraded: " + ", ".join(i["blocking"])
    if rid == "P1":
        n = len(i["unmet"])
        return f"{n} policy requirement(s) unmet (criterion below the required state or code not covered)"
    if rid == "P2":
        return (
            f"{len(i['unmet'])} criterion(s) have no counted test that is not agent-authored "
            "(required by .radius/policy.yml)"
        )
    if rid == "R3a":
        return (
            f"{len(i['finding_ids'])} tamper finding(s) at severity {i['threshold']} or above "
            "need a human look"
        )
    if rid == "R3b":
        return "a supported criterion depends on a flaky test"
    if rid == "R3c":
        return f"supported criterion rests on a criterion-to-code link below {_fmt(i['link_review_min'])}"
    return "no earlier rule fired"


def _reasons(rules: Sequence[RuleResult]) -> tuple[Reason, ...]:
    """One reason per fired rule, deciding rule first; ``rule_id`` holds the rule id.

    ``ref`` keeps the rule id too (contract 1 consumers read it there)."""

    return tuple(
        Reason(code=RULE_TABLE[r.id][1], detail=_detail(r), ref=r.id, rule_id=r.id)
        for r in rules
        if r.fired
    )


def compute_verdict_v2(
    *,
    analysis_id: str,
    head_sha: str,
    revision: int,
    criteria: Sequence[CriterionVerdict],
    uim: UimResult,
    facts: AnalysisFacts,
    config: VerdictV2Config | None = None,
    unlinked_symbols: Sequence[str] = (),
    inputs_digest: str | None = None,
    versions: dict[str, str] | None = None,
    policy: Mapping[str, Any] | None = None,
    waivers: Mapping[str, Any] | None = None,
    tamper_waived: Sequence[Mapping[str, Any]] = (),
) -> VerdictV2:
    """Apply rules R1 to R4 in priority order and return the verdict + tree."""

    cfg = config or VerdictV2Config()
    rules = evaluate_rules(criteria, uim, facts, cfg)
    decisive = decide(rules)
    digest = inputs_digest or "sha256:" + sha256_hex(
        canonical_json(
            {"criteria": tuple(criteria), "uim": uim, "facts": facts, "config": cfg.digest()}
        )
    )
    node = build_justification(rules, cfg, inputs_digest=digest, versions=versions)
    justification = node.to_dict()
    if policy:
        justification["policy"] = dict(policy)
    if waivers:
        justification["waivers"] = dict(waivers)
    problems = check_justification(
        justification,
        criterion_ids={c.criterion_id for c in criteria},
        evidence_ids={i.evidence_id for c in criteria for i in c.items},
        finding_ids={t.finding_id for t in facts.tamper},
    )
    if problems:
        msg = "justification invariants violated: " + "; ".join(problems)
        raise ValueError(msg)
    return VerdictV2(
        analysis_id=analysis_id,
        head_sha=head_sha,
        revision=revision,
        verdict=node.verdict,
        pending=decisive.id == "R2p",
        reasons=_reasons(rules),
        criteria=tuple(criteria),
        uim=uim.uim,
        uim_numerator=uim.numerator,
        uim_denominator=uim.denominator,
        intent_coverage=uim.intent_coverage,
        unlinked_symbols=tuple(unlinked_symbols),
        tamper=facts.tamper,
        justification=justification,
        config_digest=node.config_digest,
        inputs_digest=digest,
        algo_version=(versions or {}).get("verdict", ALGO_VERSION),
        profile=cfg.profile,
        policy=dict(policy or {}),
        waivers=dict(waivers or {}),
        tamper_waived=tuple(dict(w) for w in tamper_waived),
    )
