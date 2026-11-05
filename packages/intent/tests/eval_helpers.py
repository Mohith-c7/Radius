"""Builders for IN-10 evaluation tests (synthetic data only)."""

from __future__ import annotations

import json
from pathlib import Path

from radius_intent.domain import IntentSourceKind, Testability
from radius_intent.evaluation.gold import (
    EvalCase,
    EvalSource,
    EvalSpan,
    GoldCriterion,
    GoldDataset,
)
from radius_intent.evaluation.metrics import PredictedCriterion

FIXTURES = Path(__file__).parent / "fixtures" / "evaluation"
SYNTHETIC_GOLD = FIXTURES / "synthetic_gold.json"
F14_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "fixtures" / "intent"


def case(
    case_id: str = "c1",
    text: str = "x" * 60,
    gold: tuple[tuple[int, int], ...] = (),
    *,
    labels: tuple[Testability | None, ...] = (),
    ws: bool | None = None,
    author: str | None = None,
    kind: IntentSourceKind = IntentSourceKind.PR_BODY,
    source_id: str = "s",
) -> EvalCase:
    criteria = tuple(
        GoldCriterion(
            f"G{i}",
            EvalSpan(source_id, a, b),
            testability=labels[i] if i < len(labels) else None,
        )
        for i, (a, b) in enumerate(gold)
    )
    return EvalCase(
        case_id,
        (EvalSource(source_id, kind, text),),
        criteria,
        well_specified=ws,
        author_type=author,
    )


def pred(
    start: int,
    end: int,
    *,
    source_id: str = "s",
    text: str = "p",
    testability: str | None = None,
) -> PredictedCriterion:
    return PredictedCriterion(source_id, start, end, text, testability)


def dataset(*cases: EvalCase, synthetic: bool = True) -> GoldDataset:
    return GoldDataset("unit", "1", "synthetic", synthetic, tuple(cases))


def load_synthetic_doc() -> dict:
    return json.loads(SYNTHETIC_GOLD.read_text(encoding="utf-8"))
