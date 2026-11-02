"""Policy and waiver blocks stored with the verdict (justification, bundle, API).

Plain dicts, JSON-safe, deterministic for equal inputs. ``waiver_block`` is the
per-verdict **audit record**: which waivers were applied (to which findings or
criterion), which were ignored and why, and the hash of the file they came from.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from radius_evidence.policy.apply import (
    CriterionWaiverOutcome,
    FindingWaiverOutcome,
    RequirementResult,
    TamperPolicyResult,
    audit_digest,
)
from radius_evidence.policy.repo_config import (
    STATUS_ABSENT,
    STATUS_NO_BASE,
    RepoConfigResolution,
    waivers_source,
)
from radius_evidence.policy.waivers import WaiversParse


def policy_block(
    res: RepoConfigResolution,
    tamper: TamperPolicyResult,
    unmet: RequirementResult,
) -> dict[str, Any]:
    """The ``policy`` block, or ``{}`` when no policy file exists for this analysis."""

    if res.status in (STATUS_ABSENT, STATUS_NO_BASE) and not res.errors:
        return {}
    p = res.policy
    return {
        "present": p.present,
        "status": res.status,
        "mode": p.mode.value if p.mode else None,
        "source": dict(res.source),
        "head_policy": p.head_policy.value,
        "thresholds": {k: p.thresholds[k] for k in sorted(p.thresholds)},
        "tamper_thresholds": {
            "fail_on_at_least": p.fail_on_at_least,
            "review_on_at_least": p.review_on_at_least,
        },
        "provenance": [x.to_dict() for x in p.provenance],
        "ignored_head": [x.to_dict() for x in p.ignored_head],
        "requirements": [
            {"paths": list(r.paths), "min_state": r.min_state, "line": r.line, "origin": r.origin}
            for r in p.requirements
        ],
        "evidence": (
            {"require_non_agent_test": True, "paths": list(p.evidence.paths), "line": p.evidence.line}
            if p.evidence
            else None
        ),
        "exclude_paths": list(p.exclude_paths),
        "tamper": {
            "changes": list(tamper.changes),
            "acknowledgements": list(tamper.acknowledgements),
            "refused": list(tamper.refused),
            "disabled": list(tamper.disabled),
        },
        "unmet": {"required": list(unmet.required), "evidence": list(unmet.evidence)},
        "errors": list(res.errors[:50]),
        "warnings": list(res.warnings[:50]),
    }


def waiver_block(
    res: RepoConfigResolution,
    parsed: WaiversParse,
    findings: FindingWaiverOutcome,
    criteria: CriterionWaiverOutcome,
    unused: Sequence[dict[str, Any]],
    *,
    today: date,
    repo_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """The waiver audit record, or ``{}`` when there is no waivers file."""

    if res.waivers_status in (STATUS_ABSENT, STATUS_NO_BASE):
        return {}
    applied = [*findings.applied, *criteria.applied]
    ignored = [i.to_dict() for i in parsed.ignored] + list(criteria.ignored) + list(unused)
    body: dict[str, Any] = {
        "status": res.waivers_status,
        "source": waivers_source(repo_config),
        "applied": applied,
        "ignored": ignored,
        "errors": list(res.waiver_errors)[:50],
        "warnings": [str(w) for w in parsed.warnings][:50],
    }
    body["audit_digest"] = audit_digest(body)
    return {**body, "evaluated_on": today.isoformat()}
