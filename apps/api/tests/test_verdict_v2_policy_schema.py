"""Contract 3 fields in the API schema: optional, typed, and absent when unused."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from radius_api.schemas.verdict_v2 import PolicyOut, VerdictV2Out, WaiversOut

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
EXAMPLE = json.loads((ROOT / "docs" / "research" / "design" / "verdict_v2.example.08.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "docs" / "research" / "design" / "verdict_v2.schema.json").read_text(encoding="utf-8"))


def test_example_still_validates_without_the_new_fields() -> None:
    out = VerdictV2Out.model_validate(EXAMPLE)
    assert out.policy is None and out.waivers is None and out.summary.tamper_waived == 0


def test_policy_waivers_and_waived_findings_validate() -> None:
    payload = copy.deepcopy(EXAMPLE)
    payload["policy"] = {"present": True, "status": "ok", "mode": "blocking", "thresholds": {"tau_support": 0.6}}
    payload["waivers"] = {"status": "ok", "applied": [{"id": "W-1"}], "ignored": [{"id": "W-2", "code": "expired"}]}
    payload["summary"]["tamper_waived"] = 1
    payload["tamper_findings"] = [
        {
            "finding_id": "tf_1", "rule_id": "T002", "severity": "high", "path": "a.py", "reason": "r",
            "waived": True, "waiver": {"id": "W-1", "reason": "r", "owner": "alice", "expires": "2026-12-01"},
        }
    ]
    out = VerdictV2Out.model_validate(payload)
    assert out.policy and out.policy.mode == "blocking" and out.waivers and out.waivers.applied[0]["id"] == "W-1"
    assert out.tamper_findings[0].waived is True


@pytest.mark.parametrize("mode", ["loud", "", 3])
def test_policy_mode_is_a_closed_set(mode) -> None:
    with pytest.raises(ValidationError):
        PolicyOut.model_validate({"present": True, "status": "ok", "mode": mode})


def test_waivers_need_a_status() -> None:
    with pytest.raises(ValidationError):
        WaiversOut.model_validate({})


def test_json_schema_document_lists_the_new_properties_and_rules() -> None:
    props = SCHEMA["properties"]
    assert {"policy", "waivers"} <= set(props)
    rule_ids = props["justification"]["properties"]["rules"]["items"]["properties"]["id"]["enum"]
    assert "P1" in rule_ids and "P2" in rule_ids
    assert "waived" in props["tamper_findings"]["items"]["properties"]
