"""Renderer and view for contract 3: policy line, WAIVED findings, waiver audit, Check Run mapping."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from radius_github.verdict_v2 import markdown as md
from radius_github.verdict_v2.view import VerdictV2View

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
EXAMPLE = json.loads((ROOT / "docs" / "research" / "design" / "verdict_v2.example.08.json").read_text(encoding="utf-8"))

POLICY: dict[str, Any] = {
    "present": True,
    "status": "ok",
    "mode": "blocking",
    "source": {"origin": "base", "ref": "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3", "status": "ok"},
    "provenance": [
        {"key": "thresholds.tau_support", "value": 0.6, "origin": "base", "line": 4, "file": ".radius/policy.yml"},
        {"key": "tamper.rules.T002", "value": {"severity": "medium"}, "origin": "base", "line": 9},
    ],
    "ignored_head": [{"key": "thresholds.uim_max", "value": 0.4, "origin": "head", "line": 3}],
    "tamper": {
        "acknowledgements": [
            {"rule": "T005", "action": "disable", "from_severity": "high", "reason": "Security signed off, SEC-12 <b>x</b>", "line": 12}
        ],
        "refused": [{"rule": "T001", "message": "T001 reported high; disable is ignored without an 'allow_disable' reason."}],
    },
    "unmet": {
        "required": [
            {"criterion_id": "c_1", "state": "weak", "min_state": "proven", "paths": ["src/auth/**"], "line": 6},
            {"symbol_id": "s9", "state": "uncovered", "min_state": "proven", "paths": ["src/auth/**"], "line": 6},
        ]
    },
    "errors": ["line 5: thresholds.uim_max = 0.9 is outside the allowed range"],
    "warnings": ["line 7: Unknown key 'colour' is ignored."],
}
WAIVER_TAMPER = {
    "finding_id": "tf_0123456789abcdef", "rule_id": "T002", "check": "skip", "severity": "high",
    "path": "tests/a.py", "reason": "skip added", "waived": True,
    "waiver": {"id": "W-1", "reason": "tracked in SEC-42", "owner": "alice", "expires": "2026-12-01"},
}
WAIVERS = {
    "status": "ok",
    "applied": [{"id": "W-1", "kind": "finding", "target": "tf_0123456789abcdef", "owner": "alice", "reason": "tracked in SEC-42", "expires": "2026-12-01"}],
    "ignored": [
        {"id": "W-2", "code": "expired", "message": "expired on 2026-10-01.", "line": 9},
        {"id": "W-3", "code": "unused", "message": "the waiver matched nothing in this change.", "line": 15},
    ],
}


def payload(**extra: Any) -> dict[str, Any]:
    out = copy.deepcopy(EXAMPLE)
    out.update(copy.deepcopy(extra))
    return out


def view(**extra: Any) -> VerdictV2View:
    return VerdictV2View.from_payload(payload(**extra))


def test_a_payload_without_policy_renders_exactly_as_before() -> None:
    body = md.render_comment(view())
    assert "Policy" not in body and "Waivers" not in body and "WAIVED" not in body
    v = view()
    assert v.policy == {} and v.waivers == {}
    assert "policy" not in v.to_dict() and "waivers" not in v.to_dict()


def test_view_round_trips_policy_and_waivers() -> None:
    v = view(policy=POLICY, waivers=WAIVERS, tamper_findings=[WAIVER_TAMPER])
    d = v.to_dict()
    assert d["policy"]["mode"] == "blocking" and d["waivers"]["applied"][0]["id"] == "W-1"
    assert d["tamper_findings"][0]["waived"] is True and d["tamper_findings"][0]["waiver"]["owner"] == "alice"
    assert VerdictV2View.from_payload(d).to_dict() == d


def test_non_mapping_policy_values_are_ignored() -> None:
    v = view(policy="nope", waivers=[1])
    assert v.policy == {} and v.waivers == {}


def test_policy_line_and_section() -> None:
    body = md.render_comment(view(policy=POLICY))
    assert "**Policy:** blocking, from the base branch (`4f2a9d1`), 2 setting(s) applied." in body
    assert "`thresholds.tau_support` = `0.6` (policy line 4, base)" in body
    assert "Ignored (head policy may only tighten): `thresholds.uim_max` (line 3)" in body
    assert "Acknowledged disable of `T005`" in body
    assert "Ignored: T001 reported high" in body
    assert "Required `proven` for paths src/auth/\\*\\*" in body or "Required `proven` for paths src/auth/**" in body
    assert "Error: line 5" in body and "Warning: line 7" in body
    assert "<b>" not in body  # acknowledgement text is escaped


def test_policy_that_could_not_be_applied_is_stated() -> None:
    body = md.render_comment(view(policy={"present": False, "status": "invalid", "errors": ["line 1: 'version: 1' is required."]}))
    assert "could not be applied (invalid)" in body and "Error: line 1" in body


def test_waived_findings_are_tagged_with_reason_and_owner() -> None:
    body = md.render_comment(view(policy=None, waivers=WAIVERS, tamper_findings=[WAIVER_TAMPER]))
    assert "**WAIVED** `T002` **high**" in body
    assert "waiver `W-1` by alice, expires 2026-12-01: tracked in SEC-42" in body
    assert "Waivers (1 applied)" in body
    assert "Not applied `W-2`: expired" in body
    assert "W-3" not in body  # "unused" is audit-only


def test_hostile_owner_and_reason_cannot_inject_markup() -> None:
    evil = copy.deepcopy(WAIVER_TAMPER)
    evil["waiver"] = {"id": "W`1", "reason": "[click](http://evil.test) <img src=x>", "owner": "@everyone", "expires": "2026-12-01"}
    body = md.render_comment(view(tamper_findings=[evil]))
    assert "<img" not in body and "](http://evil.test)" not in body
    assert " @everyone" not in body


@pytest.mark.parametrize(
    ("verdict", "mode", "expected"),
    [
        ("verified", "blocking", "success"),
        ("needs_review", "blocking", "failure"),
        ("insufficient_evidence", "advisory", "neutral"),
        ("failed", "advisory", "neutral"),
        ("failed", None, "failure"),
    ],
)
def test_check_conclusion(verdict: str, mode: str | None, expected: str) -> None:
    policy = {"present": True, "status": "ok", "mode": mode} if mode else {}
    v = view(verdict=verdict, pending=False, policy=policy)
    assert md.check_conclusion(v) == expected
    assert md.render_check_run(v).conclusion == expected


def test_unavailable_verdict_stays_neutral_even_when_blocking() -> None:
    v = view(status="error", verdict=None, policy={"mode": "blocking"})
    assert md.check_conclusion(v) == "neutral"


def test_comment_size_stays_bounded_with_many_policy_lines() -> None:
    big = copy.deepcopy(POLICY)
    big["provenance"] = big["provenance"] * 200
    big["errors"] = ["x" * 300] * 200
    body = md.render_comment(view(policy=big, waivers={"applied": WAIVERS["applied"] * 100, "ignored": WAIVERS["ignored"] * 100}))
    assert len(body) <= md.MAX_COMMENT_CHARS
