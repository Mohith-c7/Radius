"""Apply a resolved policy and the valid waivers to the Stage B facts (VD-04, VD-05).

Pure functions over plain data. The guarantees (each covered by tests):

* a policy or waiver never touches a failed CI case or a ``contradicted``
  criterion: nothing here changes the CI case count, and a criterion waiver on a
  ``contradicted`` criterion is ignored with a visible reason;
* lowering or disabling a rule whose finding is ``high`` or ``critical`` needs an
  explicit ``allow_disable`` acknowledgement, which is recorded in the verdict;
* path exclusions only remove *changed behavioral symbols* from the coverage
  denominator. They never hide tamper findings or criteria.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.serialization import canonical_json, sha256_hex
from radius_evidence.policy.effective import EffectivePolicy
from radius_evidence.policy.globs import any_match, path_matches
from radius_evidence.policy.policy import PROTECTED_FROM, TamperRule, severity_rank
from radius_evidence.policy.waivers import IgnoredWaiver, Waiver

STATE_RANK: dict[str, int] = {"contradicted": -1, "unevidenced": 0, "weak": 1, "proven": 2}
#: A criterion in one of these states can never be waived.
NOT_WAIVABLE_STATES = frozenset({"contradicted"})


# ----------------------------------------------------------------- tamper rules


@dataclass(frozen=True, slots=True)
class TamperPolicyResult:
    findings: tuple[TamperFindingInput, ...]
    changes: tuple[dict[str, Any], ...] = ()
    acknowledgements: tuple[dict[str, Any], ...] = ()
    refused: tuple[dict[str, Any], ...] = ()
    disabled: tuple[str, ...] = ()


def _tier(rules: Sequence[TamperRule], finding: TamperFindingInput) -> list[TamperRule]:
    """Most specific entries win: ``T012:check`` before ``T012`` (engine semantics)."""

    specific = [r for r in rules if r.rule == f"{finding.rule_id}:{finding.check}"]
    if specific:
        return specific
    return [r for r in rules if r.rule == finding.rule_id]


def effective_severity(
    rules: Sequence[TamperRule], finding: TamperFindingInput
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Severity after the policy, ``None`` when disabled; plus refusals and acknowledgements."""

    original = finding.severity.strip().lower()
    protected = severity_rank(original) >= severity_rank(PROTECTED_FROM)
    current: str | None = original
    refused: list[dict[str, Any]] = []
    acks: list[dict[str, Any]] = []
    for rule in _tier(rules, finding):
        if current is None:
            break
        if rule.enabled is False and not rule.raise_only:
            if protected and not rule.allow_disable:
                refused.append(_refusal(rule, finding, "disable"))
            else:
                if protected:
                    acks.append(_ack(rule, finding, "disable"))
                current = None
                continue
        if rule.severity is None:
            continue
        new = rule.severity
        if rule.raise_only:
            new = max(new, current, key=severity_rank)
        if severity_rank(new) < severity_rank(current):
            crosses = protected and severity_rank(new) < severity_rank(PROTECTED_FROM)
            if crosses and not rule.allow_disable:
                refused.append(_refusal(rule, finding, "lower"))
                continue
            if crosses:
                acks.append(_ack(rule, finding, "lower"))
        current = new
    return current, refused, acks


def _refusal(rule: TamperRule, finding: TamperFindingInput, action: str) -> dict[str, Any]:
    return {
        "rule": rule.rule,
        "finding_id": finding.finding_id,
        "action": action,
        "line": rule.line,
        "code": "needs_allow_disable",
        "message": (
            f"{rule.rule} reported {finding.severity}; {action} is ignored without an "
            "'allow_disable' reason."
        ),
    }


def _ack(rule: TamperRule, finding: TamperFindingInput, action: str) -> dict[str, Any]:
    return {
        "rule": rule.rule,
        "finding_id": finding.finding_id,
        "action": action,
        "line": rule.line,
        "from_severity": finding.severity,
        "reason": rule.allow_disable,
        "origin": rule.origin,
    }


def apply_tamper_policy(
    findings: Iterable[TamperFindingInput], rules: Sequence[TamperRule]
) -> TamperPolicyResult:
    out: list[TamperFindingInput] = []
    changes: list[dict[str, Any]] = []
    acks: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    disabled: list[str] = []
    for f in findings:
        severity, ref, ack = effective_severity(rules, f) if rules else (f.severity, [], [])
        refused.extend(ref)
        acks.extend(ack)
        if severity is None:
            disabled.append(f.finding_id)
            changes.append({"finding_id": f.finding_id, "rule": f.rule_id, "change": "disabled"})
            continue
        if severity != f.severity.strip().lower():
            changes.append(
                {
                    "finding_id": f.finding_id,
                    "rule": f.rule_id,
                    "change": "severity",
                    "from": f.severity,
                    "to": severity,
                }
            )
            f = replace(f, severity=severity)
        out.append(f)
    return TamperPolicyResult(
        tuple(out), tuple(changes), tuple(acks), tuple(refused), tuple(sorted(disabled))
    )


# ---------------------------------------------------------------------- waivers


@dataclass(frozen=True, slots=True)
class CriterionWaiverFacts:
    state: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FindingWaiverOutcome:
    remaining: tuple[TamperFindingInput, ...]
    waived: tuple[dict[str, Any], ...]
    applied: tuple[dict[str, Any], ...]


def _waiver_matches_finding(w: Waiver, f: TamperFindingInput) -> bool:
    if w.kind == "finding":
        ok = w.target == f.finding_id
    elif w.kind == "rule":
        ok = w.target in (f.rule_id, f"{f.rule_id}:{f.check}")
    else:
        return False
    return ok and (not w.paths or any_match(w.paths, f.path))


def _record(w: Waiver, **extra: Any) -> dict[str, Any]:
    return {
        "id": w.id,
        "kind": w.kind,
        "target": w.target,
        "owner": w.owner,
        "reason": w.reason,
        "created": w.created.isoformat(),
        "expires": w.expires.isoformat(),
        "line": w.line,
        **extra,
    }


def apply_finding_waivers(
    findings: Iterable[TamperFindingInput], waivers: Sequence[Waiver]
) -> FindingWaiverOutcome:
    """Split findings into remaining and WAIVED. First matching waiver (file order) wins."""

    remaining: list[TamperFindingInput] = []
    waived: list[dict[str, Any]] = []
    used: dict[str, list[str]] = {}
    for f in findings:
        hit = next((w for w in waivers if _waiver_matches_finding(w, f)), None)
        if hit is None:
            remaining.append(f)
            continue
        used.setdefault(hit.id, []).append(f.finding_id)
        waived.append(
            {
                **f.to_dict(),
                "waived": True,
                "waiver": {
                    "id": hit.id,
                    "reason": hit.reason,
                    "owner": hit.owner,
                    "expires": hit.expires.isoformat(),
                },
            }
        )
    applied = tuple(
        _record(w, finding_ids=sorted(used[w.id])) for w in waivers if w.id in used and w.kind != "criterion"
    )
    return FindingWaiverOutcome(tuple(remaining), tuple(waived), applied)


@dataclass(frozen=True, slots=True)
class CriterionWaiverOutcome:
    waived: Mapping[str, Waiver]  # criterion id -> waiver
    applied: tuple[dict[str, Any], ...]
    ignored: tuple[dict[str, Any], ...]


def apply_criterion_waivers(
    criteria: Mapping[str, CriterionWaiverFacts], waivers: Sequence[Waiver]
) -> CriterionWaiverOutcome:
    """Waive criteria. A ``contradicted`` criterion can never be waived."""

    chosen: dict[str, Waiver] = {}
    ignored: list[dict[str, Any]] = []
    for w in waivers:
        if w.kind != "criterion":
            continue
        facts = criteria.get(w.target)
        if facts is None:
            continue  # reported as unused by the caller
        if facts.state in NOT_WAIVABLE_STATES:
            ignored.append(
                IgnoredWaiver(
                    w.id,
                    w.line,
                    "not_waivable_contradicted",
                    "a contradicted criterion cannot be waived: a failing test is not a waivable finding.",
                ).to_dict()
            )
            continue
        if w.paths and not any(path_matches(g, p) for g in w.paths for p in facts.paths):
            ignored.append(
                IgnoredWaiver(w.id, w.line, "scope_mismatch", "the criterion is not linked to code under the waiver paths.").to_dict()
            )
            continue
        chosen.setdefault(w.target, w)
    applied = tuple(_record(w, criterion_id=cid) for cid, w in sorted(chosen.items()))
    return CriterionWaiverOutcome(chosen, applied, tuple(ignored))


def unused_waivers(waivers: Sequence[Waiver], applied_ids: set[str]) -> tuple[dict[str, Any], ...]:
    return tuple(
        IgnoredWaiver(w.id, w.line, "unused", "the waiver matched nothing in this change.").to_dict()
        for w in waivers
        if w.id not in applied_ids
    )


def audit_digest(audit: Mapping[str, Any]) -> str:
    return "sha256:" + sha256_hex(canonical_json(dict(audit)))


# ----------------------------------------------------------------- requirements


@dataclass(frozen=True, slots=True)
class CriterionFacts:
    criterion_id: str
    state: str
    paths: tuple[str, ...] = ()
    counted_tests: int = 0
    non_agent_tests: int = 0


@dataclass(frozen=True, slots=True)
class SymbolFacts:
    symbol_id: str
    path: str
    covered: bool


@dataclass(frozen=True, slots=True)
class RequirementResult:
    required: tuple[dict[str, Any], ...] = ()  # P1
    evidence: tuple[dict[str, Any], ...] = ()  # P2


def evaluate_requirements(
    policy: EffectivePolicy,
    criteria: Sequence[CriterionFacts],
    symbols: Sequence[SymbolFacts],
) -> RequirementResult:
    """P1: required criterion states per path glob. P2: minimum evidence."""

    required: list[dict[str, Any]] = []
    for index, req in enumerate(policy.requirements):
        need = STATE_RANK[req.min_state]
        for c in criteria:
            if c.state == "excluded":
                continue
            if not any(path_matches(g, p) for g in req.paths for p in c.paths):
                continue
            if STATE_RANK.get(c.state, -1) < need:
                required.append(
                    {
                        "requirement": index,
                        "line": req.line,
                        "paths": list(req.paths),
                        "min_state": req.min_state,
                        "criterion_id": c.criterion_id,
                        "state": c.state,
                    }
                )
        for s in symbols:
            if not s.covered and any_match(req.paths, s.path):
                required.append(
                    {
                        "requirement": index,
                        "line": req.line,
                        "paths": list(req.paths),
                        "min_state": req.min_state,
                        "symbol_id": s.symbol_id,
                        "path": s.path,
                        "state": "uncovered",
                    }
                )
    evidence: list[dict[str, Any]] = []
    rule = policy.evidence
    if rule is not None and rule.require_non_agent_test:
        for c in criteria:
            if c.state not in ("proven", "weak"):
                continue
            if rule.paths and not any(path_matches(g, p) for g in rule.paths for p in c.paths):
                continue
            if c.non_agent_tests < 1:
                evidence.append(
                    {
                        "line": rule.line,
                        "criterion_id": c.criterion_id,
                        "counted_tests": c.counted_tests,
                        "non_agent_tests": c.non_agent_tests,
                    }
                )
    return RequirementResult(
        tuple(sorted(required, key=lambda d: canonical_json(d))),
        tuple(sorted(evidence, key=lambda d: d["criterion_id"])),
    )


def is_excluded_path(policy: EffectivePolicy, path: str) -> bool:
    return bool(policy.exclude_paths) and any_match(policy.exclude_paths, path)
