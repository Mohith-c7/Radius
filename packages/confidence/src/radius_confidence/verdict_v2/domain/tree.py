"""Justification tree (schema ``verdict-v2-justification-1``, design 3.9).

Builds the stored/served JSON from the evaluated rules and checks its
invariants: every rule exactly once in ``RULE_ORDER``; ``decided_by`` is the
first fired rule; the verdict equals the verdict of that rule; every id in
``refs`` exists in the bundle. Standard library and ``radius_evidence.domain``
only.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.versions import (
    DEFAULT_COMPONENT_VERSIONS,
    JUSTIFICATION_SCHEMA,
)

from radius_confidence.verdict_v2.domain.model import (
    RULE_ORDER,
    JustificationNode,
    RuleResult,
)
from radius_confidence.verdict_v2.domain.rules import decide, verdict_of


def thresholds_of(config: VerdictV2Config) -> dict[str, Any]:
    """The thresholds the rules used, copied from the config (never literals)."""

    return {
        "tau_support": config.support.tau_support,
        "uim_max": config.rules.uim_max,
        "min_intent_coverage": config.rules.min_intent_coverage,
        "fail_on_tamper_at_least": config.rules.fail_on_tamper_at_least,
        "review_on_tamper_at_least": config.rules.review_on_tamper_at_least,
    }


def build_justification(
    rules: Sequence[RuleResult],
    config: VerdictV2Config,
    *,
    inputs_digest: str,
    versions: dict[str, str] | None = None,
) -> JustificationNode:
    decisive = decide(rules)
    return JustificationNode(
        verdict=verdict_of(decisive.id),
        decided_by=decisive.id,
        rules=tuple(rules),
        thresholds=thresholds_of(config),
        versions=dict(DEFAULT_COMPONENT_VERSIONS if versions is None else versions),
        config_digest=f"sha256:{config.digest()}",
        profile=config.profile,
        inputs_digest=inputs_digest,
    )


def check_justification(
    justification: dict[str, Any],
    *,
    criterion_ids: Collection[str],
    evidence_ids: Collection[str],
    finding_ids: Collection[str],
) -> list[str]:
    """Return the list of violated invariants (empty means valid)."""

    errors: list[str] = []
    if justification.get("schema") != JUSTIFICATION_SCHEMA:
        errors.append("schema: unexpected value")
    rules = justification.get("rules")
    if not isinstance(rules, list):
        return [*errors, "rules: missing"]
    ids = [r.get("id") for r in rules]
    if ids != list(RULE_ORDER):
        errors.append(f"rules: ids {ids} are not exactly RULE_ORDER")
    first = next((r.get("id") for r in rules if r.get("fired") is True), None)
    if first is None:
        errors.append("rules: no rule fired")
    elif justification.get("decided_by") != first:
        errors.append(f"decided_by: {justification.get('decided_by')!r} is not the first fired rule {first!r}")
    elif justification.get("verdict") != verdict_of(first).value:
        errors.append("verdict: does not match the deciding rule")
    allowed = {
        "criterion_ids": set(criterion_ids),
        "evidence_ids": set(evidence_ids),
        "finding_ids": set(finding_ids),
    }
    for rule in rules:
        refs = rule.get("refs") or {}
        for key, values in refs.items():
            if key not in allowed:
                errors.append(f"{rule.get('id')}.refs: unknown key {key!r}")
                continue
            for value in values:
                if value not in allowed[key]:
                    errors.append(f"{rule.get('id')}.refs.{key}: unknown id {value!r}")
        if refs and rule.get("fired") is not True:
            errors.append(f"{rule.get('id')}.refs: present on a rule that did not fire")
    return errors
