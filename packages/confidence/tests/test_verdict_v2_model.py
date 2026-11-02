"""Verdict v2 model contract (VS-00): round trip and v1 independence."""

from __future__ import annotations

import ast
from pathlib import Path

import radius_confidence
from radius_confidence.verdict_v2.domain.model import (
    RULE_ORDER,
    CriterionVerdict,
    JustificationNode,
    RuleResult,
    Verdict,
    VerdictV2,
)
from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.model import Reason

SHA = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
PKG = Path(radius_confidence.__file__).parent


def _verdict() -> VerdictV2:
    node = JustificationNode(
        verdict=Verdict.INSUFFICIENT_EVIDENCE,
        decided_by="R2b",
        rules=(
            RuleResult(
                "R2b",
                "unproven intent mass",
                True,
                {"uim": 0.75},
                {"criterion_ids": ("c_1",)},
            ),
        ),
        thresholds={"uim_max": 0.2},
    )
    return VerdictV2(
        analysis_id="a-1",
        head_sha=SHA,
        revision=1,
        verdict=Verdict.INSUFFICIENT_EVIDENCE,
        pending=False,
        reasons=(Reason("unproven_intent_mass", "uim 0.75 exceeds 0.20", "R2b"),),
        criteria=(
            CriterionVerdict(
                "c_1",
                "text",
                1.0,
                "behavioral_testable",
                "confirmed",
                SupportState.WEAK,
                0.432,
                0.432,
                (),
                (Flag.STATIC_ONLY,),
            ),
        ),
        uim=0.75,
        uim_numerator=3.0,
        uim_denominator=4.0,
        intent_coverage=1.0,
        unlinked_symbols=(),
        tamper=(TamperFindingInput("tf_1", "T001", "x", "high", 0.9, "t.py"),),
        justification=node.to_dict(),
        config_digest="c" * 64,
        inputs_digest="i" * 64,
    )


def test_verdict_v2_round_trips() -> None:
    verdict = _verdict()
    assert VerdictV2.from_json(verdict.to_json()) == verdict
    assert JustificationNode.from_dict(verdict.justification).decided_by == "R2b"


def test_verdict_values_and_rule_order() -> None:
    assert {v.value for v in Verdict} == {
        "verified",
        "failed",
        "insufficient_evidence",
        "needs_review",
    }
    assert RULE_ORDER[0] == "R1a"
    assert RULE_ORDER[-1] == "R4"
    assert len(RULE_ORDER) == 12


def test_v1_confidence_modules_do_not_import_verdict_v2() -> None:
    for layer in ("domain", "application", "infrastructure", "dto", "interfaces"):
        for path in (PKG / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert "verdict_v2" not in name, f"{path}: {name}"
                    assert not name.startswith("radius_evidence"), f"{path}: {name}"
