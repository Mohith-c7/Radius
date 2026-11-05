"""Effective policy: base policy (+ optional tighten-only head policy) over the defaults.

``resolve_policy`` is the only place where a ``Policy`` becomes a
``VerdictV2Config`` overlay. The base-branch policy is authoritative. A policy
read from the PR head is only ever consulted when the *base* policy opted in
with ``head_policy: tighten_only``, and then each of its settings is accepted
only if it is at least as strict as what the base side already gives; anything
that would loosen is dropped and reported. ``at_least_as_strict`` states the
order so tests can check the guarantee as a property.

Every applied setting is recorded as ``Provenance`` (key, value, origin, line)
for the justification tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.policy.policy import (
    POLICY_PATH,
    STRICT_DIRECTION,
    EvidenceRule,
    HeadPolicyMode,
    Mode,
    Policy,
    Requirement,
    TamperRule,
    severity_rank,
)

#: Where each threshold lives in ``VerdictV2Config``.
CONFIG_FIELDS: dict[str, str] = {
    "tau_support": "support.tau_support",
    "uim_max": "rules.uim_max",
    "intent_coverage_min": "rules.min_intent_coverage",
    "link_review_min": "rules.link_review_min",
    "cap_static": "quality.cap_static",
}


def default_threshold(config: VerdictV2Config, key: str) -> float:
    group, name = CONFIG_FIELDS[key].split(".")
    return float(getattr(getattr(config, group), name))


def overlay_thresholds(
    config: VerdictV2Config,
    thresholds: dict[str, float],
    fail_on: str | None,
    review_on: str | None,
) -> VerdictV2Config:
    """Return ``config`` with the given threshold values replaced."""

    support = replace(config.support, tau_support=thresholds.get("tau_support", config.support.tau_support))
    quality = replace(config.quality, cap_static=thresholds.get("cap_static", config.quality.cap_static))
    rules = replace(
        config.rules,
        uim_max=thresholds.get("uim_max", config.rules.uim_max),
        min_intent_coverage=thresholds.get("intent_coverage_min", config.rules.min_intent_coverage),
        link_review_min=thresholds.get("link_review_min", config.rules.link_review_min),
        fail_on_tamper_at_least=fail_on or config.rules.fail_on_tamper_at_least,
        review_on_tamper_at_least=review_on or config.rules.review_on_tamper_at_least,
    )
    return replace(config, support=support, quality=quality, rules=rules)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which setting came from which policy line."""

    key: str
    value: Any
    origin: str  # base | head
    line: int
    file: str = POLICY_PATH

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "origin": self.origin,
            "file": self.file,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    present: bool = False
    mode: Mode | None = None
    thresholds: dict[str, float] = field(default_factory=dict)
    fail_on_at_least: str | None = None
    review_on_at_least: str | None = None
    tamper_rules: tuple[TamperRule, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    evidence: EvidenceRule | None = None
    exclude_paths: tuple[str, ...] = ()
    head_policy: HeadPolicyMode = HeadPolicyMode.IGNORE
    provenance: tuple[Provenance, ...] = ()
    #: Head-policy settings dropped because they would loosen the base policy.
    ignored_head: tuple[Provenance, ...] = ()

    @property
    def has_rules(self) -> bool:
        """True when the policy adds verdict rules P1/P2."""

        return bool(self.requirements) or self.evidence is not None


NO_POLICY = EffectivePolicy()


def apply_to_config(effective: EffectivePolicy, base: VerdictV2Config | None = None) -> VerdictV2Config:
    return overlay_thresholds(
        base or VerdictV2Config(),
        effective.thresholds,
        effective.fail_on_at_least,
        effective.review_on_at_least,
    )


def _stricter(key: str, candidate: float, current: float) -> bool:
    return (candidate - current) * STRICT_DIRECTION[key] >= 0


def resolve_policy(
    base: Policy | None,
    head: Policy | None = None,
    defaults: VerdictV2Config | None = None,
) -> EffectivePolicy:
    """Combine the policies. ``head`` is ignored unless ``base`` opted in."""

    if base is None:
        return NO_POLICY
    cfg = defaults or VerdictV2Config()
    prov: list[Provenance] = []
    dropped: list[Provenance] = []

    thresholds = dict(base.thresholds)
    for key, value in sorted(base.thresholds.items()):
        prov.append(Provenance(f"thresholds.{key}", value, "base", base.lines.get(f"thresholds.{key}", 0)))
    fail_on, review_on = base.fail_on_at_least, base.review_on_at_least
    for key, value in (("fail_on_at_least", fail_on), ("review_on_at_least", review_on)):
        if value is not None:
            prov.append(Provenance(f"tamper.{key}", value, "base", base.lines.get(f"tamper.{key}", 0)))
    mode = base.mode
    if mode is not None:
        prov.append(Provenance("mode", mode.value, "base", base.lines.get("mode", 0)))
    rules = list(base.tamper_rules)
    for r in base.tamper_rules:
        prov.append(Provenance(f"tamper.rules.{r.rule}", _rule_value(r), "base", r.line))
    requirements = list(base.requirements)
    for i, req in enumerate(base.requirements):
        prov.append(Provenance(f"require[{i}]", {"paths": list(req.paths), "min_state": req.min_state}, "base", req.line))
    evidence = base.evidence
    if evidence is not None:
        prov.append(Provenance("evidence.require_non_agent_test", True, "base", evidence.line))
    exclude = base.exclude_paths

    if head is not None and base.head_policy is HeadPolicyMode.TIGHTEN_ONLY:
        for key, value in sorted(head.thresholds.items()):
            line = head.lines.get(f"thresholds.{key}", 0)
            current = thresholds.get(key, default_threshold(cfg, key))
            entry = Provenance(f"thresholds.{key}", value, "head", line)
            if _stricter(key, value, current):
                thresholds[key] = value
                prov.append(entry)
            else:
                dropped.append(entry)
        cur_fail = fail_on or cfg.rules.fail_on_tamper_at_least
        cur_review = review_on or cfg.rules.review_on_tamper_at_least
        if head.fail_on_at_least is not None:
            entry = Provenance("tamper.fail_on_at_least", head.fail_on_at_least, "head", head.lines.get("tamper.fail_on_at_least", 0))
            if severity_rank(head.fail_on_at_least) <= severity_rank(cur_fail):
                fail_on = head.fail_on_at_least
                prov.append(entry)
            else:
                dropped.append(entry)
        if head.review_on_at_least is not None:
            entry = Provenance("tamper.review_on_at_least", head.review_on_at_least, "head", head.lines.get("tamper.review_on_at_least", 0))
            if severity_rank(head.review_on_at_least) <= severity_rank(cur_review):
                review_on = head.review_on_at_least
                prov.append(entry)
            else:
                dropped.append(entry)
        if head.mode is Mode.BLOCKING and mode is not Mode.BLOCKING:
            mode = Mode.BLOCKING
            prov.append(Provenance("mode", "blocking", "head", head.lines.get("mode", 0)))
        elif head.mode is Mode.ADVISORY and mode is Mode.BLOCKING:
            dropped.append(Provenance("mode", "advisory", "head", head.lines.get("mode", 0)))
        for r in head.tamper_rules:
            if r.enabled is False or r.allow_disable:  # never honoured from the head
                dropped.append(Provenance(f"tamper.rules.{r.rule}", _rule_value(r), "head", r.line))
            if r.severity is not None:
                rules.append(TamperRule(r.rule, r.line, r.severity, None, None, True, "head"))
                prov.append(
                    Provenance(f"tamper.rules.{r.rule}", {"severity": r.severity, "raise_only": True}, "head", r.line)
                )
        for i, req in enumerate(head.requirements):
            requirements.append(replace(req, origin="head"))
            prov.append(Provenance(f"require[{len(base.requirements) + i}]", {"paths": list(req.paths), "min_state": req.min_state}, "head", req.line))
        if head.evidence is not None and evidence is None:
            evidence = replace(head.evidence, origin="head")
            prov.append(Provenance("evidence.require_non_agent_test", True, "head", head.evidence.line))
        for glob in head.exclude_paths:
            dropped.append(Provenance("exclude.paths", glob, "head", head.lines.get("exclude", 0)))

    # Keep review at or below fail after a merge (never makes anything looser).
    cur_fail = fail_on or cfg.rules.fail_on_tamper_at_least
    cur_review = review_on or cfg.rules.review_on_tamper_at_least
    if severity_rank(cur_review) > severity_rank(cur_fail):
        review_on = cur_fail

    return EffectivePolicy(
        present=True,
        mode=mode,
        thresholds=thresholds,
        fail_on_at_least=fail_on,
        review_on_at_least=review_on,
        tamper_rules=tuple(rules),
        requirements=tuple(requirements),
        evidence=evidence,
        exclude_paths=tuple(exclude),
        head_policy=base.head_policy,
        provenance=tuple(prov),
        ignored_head=tuple(dropped),
    )


def _rule_value(rule: TamperRule) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if rule.severity is not None:
        out["severity"] = rule.severity
    if rule.enabled is not None:
        out["enabled"] = rule.enabled
    if rule.allow_disable:
        out["allow_disable"] = True  # the reason text goes to the acknowledgement record
    return out


def at_least_as_strict(a: EffectivePolicy, b: EffectivePolicy, defaults: VerdictV2Config | None = None) -> bool:
    """True when ``a`` is at least as strict as ``b`` on every dimension that can loosen a verdict.

    Used by the property tests: a head policy merged under ``tighten_only`` must
    satisfy ``at_least_as_strict(merged, base_only)``.
    """

    cfg = defaults or VerdictV2Config()
    for key in CONFIG_FIELDS:
        va = a.thresholds.get(key, default_threshold(cfg, key))
        vb = b.thresholds.get(key, default_threshold(cfg, key))
        if not _stricter(key, va, vb):
            return False
    for attr, default in (
        ("fail_on_at_least", cfg.rules.fail_on_tamper_at_least),
        ("review_on_at_least", cfg.rules.review_on_tamper_at_least),
    ):
        if severity_rank(getattr(a, attr) or default) > severity_rank(getattr(b, attr) or default):
            return False
    if b.mode is Mode.BLOCKING and a.mode is not Mode.BLOCKING:
        return False
    if not {(r.paths, r.min_state) for r in b.requirements} <= {(r.paths, r.min_state) for r in a.requirements}:
        return False
    if b.evidence is not None and a.evidence is None:
        return False
    return set(a.exclude_paths) <= set(b.exclude_paths)
