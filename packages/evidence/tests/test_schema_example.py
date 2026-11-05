"""The design example payload validates against the JSON schema and round-trips.

A tiny stdlib validator covers the keywords the schema uses (no new dependency).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from radius_evidence.domain.enums import Flag, Outcome, SupportState
from radius_evidence.domain.quality import EvidenceQuality
from radius_evidence.domain.serialization import canonical_json

DESIGN = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
) / "docs" / "research" / "design"
SCHEMA = json.loads((DESIGN / "verdict_v2.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((DESIGN / "verdict_v2.example.08.json").read_text(encoding="utf-8"))

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return a list of violations of the JSON-Schema subset used by the design."""

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [*errors, f"{path}: expected type {names}, got {type(value).__name__}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum")
    if isinstance(value, str) and "pattern" in schema:
        if not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{path}.{key}")
            elif isinstance(extra, dict):
                errors += validate(item, extra, f"{path}.{key}")
            elif extra is False:
                errors.append(f"{path}: unexpected property {key!r}")
    return errors


def test_example_validates_against_schema() -> None:
    assert validate(EXAMPLE, SCHEMA) == []


def test_validator_rejects_broken_payloads() -> None:
    for mutate in (
        lambda d: d.pop("verdict"),
        lambda d: d.update(verdict="maybe"),
        lambda d: d.update(head_sha="XYZ"),
        lambda d: d.update(score=1.0),
        lambda d: d["criteria"][0].update(state="partially_evidenced"),
        lambda d: d["criteria"][0].update(S=1.5),
        lambda d: d["criteria"][0]["flags"].append("made_up"),
    ):
        payload = copy.deepcopy(EXAMPLE)
        mutate(payload)
        assert validate(payload, SCHEMA), "mutation should violate the schema"


def test_example_survives_a_canonical_json_round_trip() -> None:
    text = canonical_json(EXAMPLE)
    assert json.loads(text) == EXAMPLE
    assert canonical_json(json.loads(text)) == text
    assert validate(json.loads(text), SCHEMA) == []


def test_example_items_parse_as_evidence_quality() -> None:
    count = 0
    for criterion in EXAMPLE["criteria"]:
        for item in criterion["items"]:
            row = {**item, "criterion_id": criterion["criterion_id"], "cap_static": 0.6}
            parsed = EvidenceQuality.from_dict(row)
            out = parsed.to_dict()
            for key, value in item.items():
                if key in {"test_id", "outcome"}:
                    continue
                assert out[key] == pytest.approx(value), key
            count += 1
    assert count > 0


def test_schema_enums_match_the_python_enums() -> None:
    crit = SCHEMA["properties"]["criteria"]["items"]["properties"]
    assert set(crit["state"]["enum"]) == {s.value for s in SupportState}
    assert set(crit["flags"]["items"]["enum"]) == {f.value for f in Flag}
    outcomes = crit["items"]["items"]["properties"]["outcome"]["enum"]
    assert set(outcomes) == {o.value for o in Outcome}
