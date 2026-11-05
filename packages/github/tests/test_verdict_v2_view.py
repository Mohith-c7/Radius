"""``VerdictV2View.from_payload`` parses the design example and tolerates bad input."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import radius_github
from radius_github.verdict_v2.view import VerdictV2View

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
EXAMPLE = json.loads(
    (ROOT / "docs/research/design/verdict_v2.example.08.json").read_text(
        encoding="utf-8"
    )
)


def test_example_payload_parses() -> None:
    view = VerdictV2View.from_payload(EXAMPLE)
    assert view.verdict == "insufficient_evidence"
    assert view.pending is False
    assert view.summary.criteria_total == 4
    assert view.summary.uim == 0.75
    assert [c.state for c in view.criteria] == [
        "proven",
        "weak",
        "unevidenced",
        "unevidenced",
    ]
    assert view.criteria[0].items[0].term == 0.432
    assert view.next_actions[0].code == "no_linked_test"
    assert view.v1 is not None
    assert view.v1["score_kind"] == "heuristic_uncalibrated"
    assert view.justification["decided_by"] == "R2b"


def test_view_round_trips_through_its_own_dict() -> None:
    view = VerdictV2View.from_payload(EXAMPLE)
    assert VerdictV2View.from_payload(view.to_dict()) == view
    assert json.loads(json.dumps(view.to_dict())) == view.to_dict()


def test_unknown_and_malformed_fields_are_tolerated() -> None:
    payload = {
        **EXAMPLE,
        "future": {"x": 1},
        "criteria": [
            {"criterion_id": 7, "text": None, "items": "nope", "S": "x"},
            "junk",
        ],
        "verdict": 3,
        "pending": "yes",
        "summary": [],
    }
    view = VerdictV2View.from_payload(payload)
    assert view.verdict is None
    assert view.pending is False
    assert len(view.criteria) == 1
    assert view.criteria[0].criterion_id == ""
    assert view.summary.criteria_total == 0


def test_empty_payload_gives_neutral_view() -> None:
    view = VerdictV2View.from_payload({})
    assert view.verdict is None
    assert view.criteria == ()
    assert view.revision == 1


def test_verdict_v2_package_imports_no_domain_package() -> None:
    folder = Path(radius_github.__file__).parent / "verdict_v2"
    stdlib = sys.stdlib_module_names
    for path in folder.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                root = node.module.split(".")[0]
                assert root in stdlib or root == "radius_github", (
                    f"{path.name}: {node.module}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in stdlib
