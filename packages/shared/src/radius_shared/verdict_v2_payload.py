"""Served/published verdict v2 payload built from a stored bundle (VS-07, VS-09).

Pure and stdlib only, so the API (served JSON) and the worker (renderer input)
build byte-identical payloads. The payload conforms to
``docs/research/design/verdict_v2.schema.json``.

Bundle contract (schema ``verdict-v2-bundle-1``), written by the worker scoring
step and stored verbatim in ``verdict_v2.bundle``::

    {
      "schema": "verdict-v2-bundle-1",
      "analysis_id": str, "head_sha": str(40 hex),
      "status": "ok" | "error" | "skipped",
      "inputs_digest": str, "config_digest": str,
      "algo_version": str, "profile": str,
      "verdict": VerdictV2.to_dict() | None,      # radius_confidence.verdict_v2
      "evidence_items": [EvidenceItem.to_dict()],  # optional; supplies outcomes
      "stage_a": StageAInput.to_dict(),            # optional; lets Stage B rerun
      "next_actions": [{code, text, criterion_id}],  # optional
      "reason_code": str | None, "error_detail": str | None,
      "fallback": "v1" | None, "truncated": bool
    }

``score`` is always ``null`` and ``score_kind`` is ``"none"``: v2 has no number
to calibrate. The only score in the payload is the labelled ``v1`` block.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from radius_shared.verdict_v2_wording import presentation

BUNDLE_SCHEMA = "verdict-v2-bundle-1"
#: Mirrors ``radius_evidence.domain.versions.CONTRACT_VERSION`` (a test keeps them equal).
CONTRACT_VERSION = "verdict-v2-contract-5"
STATES = ("proven", "weak", "unevidenced", "contradicted", "excluded")
SEVERITIES = ("critical", "high", "medium", "low")

_ACTION_TEXT = {
    "no_linked_test": (
        "No test is linked to this criterion. Add a test that checks it, or add a "
        "tests hint in .radius/intent.yml."
    ),
    "weak_assertion": (
        "The linked tests assert too little. Assert the exact expected value."
    ),
    "single_test": (
        "Support is below the threshold. Add another independent case or a "
        "boundary case."
    ),
    "failing_test": "A linked test fails. Fix the code or the test.",
    "needs_typed_evidence": (
        "This criterion needs non-functional evidence that alpha does not collect."
    ),
}


@dataclass(frozen=True, slots=True)
class StoredVerdict:
    """A stored ``verdict_v2`` row as plain data (what the repository returns)."""

    row_id: str
    organization_id: str
    analysis_id: str
    head_sha: str
    revision: int
    inputs_digest: str
    status: str
    mode: str
    verdict: str | None
    pending: bool
    reason_code: str | None
    algo_version: str
    profile: str
    config_digest: str
    bundle: Mapping[str, Any]
    justification: Mapping[str, Any] | None
    error_detail: str | None
    fallback: str | None
    published_at: datetime | None
    published_digest: str | None
    publish_error: str | None
    computed_at: datetime


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _maps(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, Mapping)]


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def derive_next_actions(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fixed-text actions per criterion; no untrusted text is interpolated."""

    actions: list[dict[str, Any]] = []
    for criterion in criteria:
        state = criterion.get("state")
        flags = set(criterion.get("flags") or [])
        cid = criterion.get("criterion_id")
        code: str | None = None
        if state == "contradicted":
            code = "failing_test"
        elif state in ("proven", "excluded"):
            code = None
        elif "needs_typed_evidence" in flags:
            code = "needs_typed_evidence"
        elif "no_linked_test" in flags:
            code = "no_linked_test"
        elif "no_strong_assertion" in flags:
            code = "weak_assertion"
        else:
            code = "single_test"
        if code is not None:
            actions.append(
                {"criterion_id": cid, "code": code, "text": _ACTION_TEXT[code]}
            )
    return actions


_RULE_ID = re.compile(r"^[RP]\d[a-z]?$")

_MUTATION_ITEM_KEYS = ("basis", "d_mut", "d_mut_lcb", "mutation_n", "mutation_killed")

#: The documented per-item keys (``verdict_v2.schema.json``); bundle rows may carry more
#: (``criterion_id``, ``lambda_kind``, ``cap_static`` ...) that are not part of the contract.
_ITEM_KEYS = (
    "evidence_id", "test_id", "outcome", "a_static", "d_eff", "i", "f", "flaky_f",
    "tamper_penalty", "q", "l_cs", "l_st", "r_ct", "l", "term", "group_symbol",
    "rank_in_group", "discount", "contribution", "status",
    # contract 5 (present only for mutation-measured rows)
    "basis", "d_mut", "d_mut_lcb", "mutation_n", "mutation_killed",
)


def _outcome_from_status(status: Any) -> str:
    """Outcome implied by a quality row status when ``evidence_items`` were dropped (B-17).

    ``gated:outcome_failed`` / ``gated:outcome_error`` / ``gated:outcome_skipped`` name the
    outcome; ``counted`` means the test ran and passed. Anything else is ``not_run``.
    """

    if isinstance(status, str):
        if status == "counted":
            return "passed"
        if status.startswith("gated:outcome_"):
            tail = status.removeprefix("gated:outcome_")
            if tail in ("failed", "error", "skipped", "flaky"):
                return tail
    return "not_run"


def _criterion(
    raw: Mapping[str, Any], outcomes: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in _maps(raw.get("items")):
        data = dict(item)
        path = data.pop("path", None)
        evidence = outcomes.get(str(data.get("evidence_id")), {})
        test_id = (
            (path.get("test_id") if isinstance(path, Mapping) else None)
            or evidence.get("subject_id")
            or ""
        )
        data["test_id"] = test_id
        data["outcome"] = (
            evidence.get("outcome") or data.get("outcome") or _outcome_from_status(data.get("status"))
        )
        row = {k: data[k] for k in _ITEM_KEYS if k in data}
        if data.get("mutation_n") is None:  # contract 5: only mutation-measured rows carry these
            for key in _MUTATION_ITEM_KEYS:
                row.pop(key, None)
        items.append(row)
    best = raw.get("best_link")
    mutation = raw.get("mutation")
    extra: dict[str, Any] = {}
    if isinstance(mutation, Mapping) and mutation:  # contract 5, only with RADIUS_FEATURE_MUTATION
        extra = {
            "evidence_basis": str(mutation.get("basis") or "static_only"),
            "mutation": dict(mutation),
        }
    confirmed_by = raw.get("confirmed_by")
    if isinstance(confirmed_by, str) and confirmed_by:  # B-07, optional
        extra = {**extra, "confirmed_by": confirmed_by[:160]}
    return {
        **extra,
        "criterion_id": raw.get("criterion_id", ""),
        "text": raw.get("text", ""),
        "state": raw.get("state", "unevidenced"),
        "S": raw.get("S", 0.0),
        "S_raw": raw.get("S_raw", 0.0),
        "weight": raw.get("weight", 1.0),
        "testability": raw.get("testability", ""),
        "lifecycle": raw.get("lifecycle", ""),
        "flags": list(raw.get("flags") or []),
        "provenance": raw.get("provenance") or "author_pr_body",
        "hints": [
            {k: str(h.get(k, "")) for k in ("kind", "value", "provenance")}
            for h in _maps(raw.get("hints"))
        ],
        "reasons": [
            {k: v for k, v in r.items() if not (k == "rule_id" and v is None)}
            for r in _maps(raw.get("reasons"))
        ],
        "best_link": dict(best) if isinstance(best, Mapping) and best else None,
        "items": items,
    }


MAX_SUGGESTED_TESTS = 5
MAX_SUGGESTED_CODE = 2500


def suggested_tests(raw: Any) -> list[dict[str, Any]]:
    """Sanitised ``suggested_tests`` (DEC-034): LLM-proposed, gated, never run, never evidence.

    The flags are forced here, whatever the stored bundle says, so no reader can be told a
    suggestion was executed or counts as evidence.
    """

    out: list[dict[str, Any]] = []
    for item in _maps(raw)[:MAX_SUGGESTED_TESTS]:
        code = item.get("test_code")
        cid = item.get("criterion_id")
        if not (isinstance(code, str) and isinstance(cid, str) and code.strip()):
            continue
        imports = item.get("imports")
        out.append(
            {
                "criterion_id": cid,
                "test_code": code[:MAX_SUGGESTED_CODE],
                "a_static": item["a_static"]
                if isinstance(item.get("a_static"), (int, float))
                and not isinstance(item.get("a_static"), bool)
                else 0.0,
                "imports": {
                    str(m): [str(n) for n in names if isinstance(n, str)]
                    for m, names in imports.items()
                    if isinstance(names, list)
                }
                if isinstance(imports, Mapping)
                else {},
                "model": item["model"] if isinstance(item.get("model"), str) else "",
                "provenance": "llm_proposed",
                "executed": False,
                "evidence": False,
            }
        )
    return out


def build_payload(
    stored: StoredVerdict,
    *,
    v1: Mapping[str, Any] | None = None,
    dashboard_url: str | None = None,
) -> dict[str, Any]:
    """Return the JSON object served at ``GET /analyses/{id}/verdict-v2``."""

    bundle = stored.bundle
    verdict = bundle.get("verdict") if isinstance(bundle.get("verdict"), Mapping) else {}
    ok = stored.status == "ok" and bool(verdict)
    outcomes = {
        str(e.get("evidence_id")): e
        for e in _maps(bundle.get("evidence_items"))
        if e.get("evidence_id")
    }
    criteria = (
        [_criterion(c, outcomes) for c in _maps(verdict.get("criteria"))] if ok else []
    )
    counts = {state: 0 for state in STATES}
    for criterion in criteria:
        if criterion["state"] in counts:
            counts[criterion["state"]] += 1
    tamper_raw = _maps(verdict.get("tamper")) if ok else []
    tamper_counts = {sev: 0 for sev in SEVERITIES}
    for finding in tamper_raw:
        sev = str(finding.get("severity"))
        if sev in tamper_counts:
            tamper_counts[sev] += 1
    waived_raw = _maps(verdict.get("tamper_waived")) if ok else []
    justification = dict(stored.justification or {}) if ok else {}
    decided_by = _as_str(justification.get("decided_by"))
    reasons = [dict(r) for r in _maps(verdict.get("reasons"))] if ok else []
    for index, reason in enumerate(reasons):
        if reason.get("rule_id"):
            continue
        ref = reason.get("ref")
        if isinstance(ref, str) and _RULE_ID.match(ref):  # contract 1 bundles kept it in ref
            reason["rule_id"] = ref
        elif index == 0 and decided_by:
            reason["rule_id"] = decided_by
        else:
            reason.pop("rule_id", None)
    if not ok:
        reasons = [
            {
                "code": stored.reason_code or stored.status,
                "detail": "Verdict v2 is not available for this analysis.",
            }
        ]
    next_actions = bundle.get("next_actions")
    if not isinstance(next_actions, list):
        next_actions = derive_next_actions(criteria) if ok else []
    uim = verdict.get("uim") if ok else 0.0
    coverage = verdict.get("intent_coverage") if ok else 0.0
    payload: dict[str, Any] = {
        "verdict_version": 2,
        "algo_version": stored.algo_version,
        "profile": stored.profile,
        "mode": stored.mode,
        "status": stored.status,
        "analysis_id": stored.analysis_id,
        "head_sha": stored.head_sha,
        "revision": stored.revision,
        "computed_at": _iso(stored.computed_at),
        "verdict": stored.verdict if ok else None,
        "pending": bool(stored.pending) if ok else False,
        "reasons": reasons,
        "score": None,
        "score_kind": "none",
        "trust_probability": None,
        "contract_version": CONTRACT_VERSION,
        "alpha": True,
        "calibrated": False,
        "evidence_basis": (verdict.get("evidence_basis") if ok else None) or "static_only",
        "presentation": presentation(
            stored.verdict if ok else None,
            counts["proven"],
            len(criteria),
            author_hint_criteria=sum(
                1 for c in criteria if "author_supplied_hint" in c["flags"]
            ),
            evidence_basis=(verdict.get("evidence_basis") if ok else None) or "static_only",
        ),
        "summary": {
            "criteria_total": len(criteria),
            "author_hint_criteria": sum(
                1 for c in criteria if "author_supplied_hint" in c["flags"]
            ),
            "proven": counts["proven"],
            "weak": counts["weak"],
            "unevidenced": counts["unevidenced"],
            "contradicted": counts["contradicted"],
            "excluded": counts["excluded"],
            "uim": uim if isinstance(uim, (int, float)) else 0.0,
            "intent_coverage": coverage if isinstance(coverage, (int, float)) else 0.0,
            "tamper": tamper_counts,
            "evidence_basis": verdict.get("evidence_basis", "static_only")
            if ok
            else "static_only",
        },
        "criteria": criteria,
        "tamper_findings": [dict(t) for t in tamper_raw] + [dict(w) for w in waived_raw],
        "unlinked_symbols": [
            s for s in (verdict.get("unlinked_symbols") or []) if isinstance(s, str)
        ]
        if ok
        else [],
        "next_actions": next_actions,
        "justification": justification,
        "v1": dict(v1) if v1 is not None else None,
        "dashboard_url": dashboard_url,
        "error": None,
    }
    if ok and isinstance(bundle.get("mutation"), Mapping) and bundle["mutation"]:
        payload["mutation"] = dict(bundle["mutation"])
    if waived_raw:
        payload["summary"]["tamper_waived"] = len(waived_raw)
    if ok and isinstance(verdict.get("policy"), Mapping) and verdict["policy"]:
        payload["policy"] = dict(verdict["policy"])
    if ok and isinstance(verdict.get("waivers"), Mapping) and verdict["waivers"]:
        payload["waivers"] = dict(verdict["waivers"])
    if ok:
        degraded = [
            d[:120]
            for d in (bundle.get("degraded") if isinstance(bundle.get("degraded"), list) else [])
            if isinstance(d, str)
        ][:50]
        if degraded:  # B-20: the analysis degradation markers, blocking ones included
            payload["degraded"] = degraded
        suggestions = suggested_tests(bundle.get("suggested_tests"))
        if suggestions:
            payload["suggested_tests"] = suggestions
    if stored.status != "ok":
        payload["error"] = {
            "code": stored.reason_code or stored.status,
            **({"fallback": stored.fallback} if stored.fallback else {}),
        }
    return payload
