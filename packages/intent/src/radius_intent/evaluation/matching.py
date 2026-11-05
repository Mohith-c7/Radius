"""One-to-one matching of predicted criteria to gold criteria (IN-10).

Preregistered rule (PREREGISTRATION 5.1): a predicted criterion matches a gold
criterion when their source spans have character IoU >= 0.5 (the threshold is
configurable; 0.5 is an "initial guess" frozen with the preregistration).
Secondary rules compare statement text instead of spans.

Matching is one-to-one and greedy: all candidate pairs above the threshold are
ordered by score descending, then predicted index ascending, then gold index
ascending, and taken when both sides are still free. This is deterministic and
independent of dictionary or set ordering. Greedy is not guaranteed to
maximise the number of matches (an optimal assignment could differ in rare
crossing cases); it is the same rule as ``extraction.metrics.score_extraction``.

Consequences worth knowing:

* Spans are compared only inside the same ``source_id``.
* A duplicate gold criterion (same span twice) needs two predictions; a
  prediction can never be credited twice. A prediction that splits a compound
  gold statement into two halves matches at most one gold item; list the
  halves as ``alt_spans`` of separate gold items if both are acceptable.
* Spans that merely touch (``[0,5)`` and ``[5,9)``) have IoU 0.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from radius_intent.domain import normalize_text

_EPS = 1e-12
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SpanRef:
    """A half-open span in a named source (matching-side view)."""

    source_id: str
    start: int
    end: int


@dataclass(frozen=True)
class Match:
    """A matched pair of indices with its score (IoU or text similarity)."""

    pred_index: int
    gold_index: int
    score: float


def span_iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Character IoU of two half-open ranges (0.0 when empty or disjoint)."""
    inter = min(a_end, b_end) - max(a_start, b_start)
    if inter <= 0:
        return 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter / union if union > 0 else 0.0


def best_iou(pred: SpanRef, gold_spans: Sequence[SpanRef]) -> float:
    """Best IoU between ``pred`` and any same-source span of one gold item."""
    best = 0.0
    for g in gold_spans:
        if g.source_id == pred.source_id:
            best = max(best, span_iou(pred.start, pred.end, g.start, g.end))
    return best


def text_tokens(text: str) -> frozenset[str]:
    """Word tokens of the normalized text (NFKC, casefolded)."""
    return frozenset(_TOKEN.findall(normalize_text(text)))


def text_similarity(a: str, b: str) -> float:
    """Token Jaccard of two statements; identical normalized text scores 1.0."""
    na, nb = normalize_text(a), normalize_text(b)
    if na == nb:
        return 1.0
    ta, tb = frozenset(_TOKEN.findall(na)), frozenset(_TOKEN.findall(nb))
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def greedy_one_to_one(pairs: Sequence[tuple[float, int, int]]) -> list[Match]:
    """Take (score, pred, gold) candidates greedily; see the module docstring."""
    used_p: set[int] = set()
    used_g: set[int] = set()
    out: list[Match] = []
    for score, i, j in sorted(pairs, key=lambda t: (-t[0], t[1], t[2])):
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append(Match(i, j, score))
    return sorted(out, key=lambda m: (m.pred_index, m.gold_index))


def match_by_iou(
    preds: Sequence[SpanRef],
    gold: Sequence[Sequence[SpanRef]],
    threshold: float = 0.5,
) -> list[Match]:
    """Match predictions to gold items (each a tuple of acceptable spans)."""
    pairs = []
    for i, p in enumerate(preds):
        for j, spans in enumerate(gold):
            score = best_iou(p, spans)
            if score > 0 and score + _EPS >= threshold:
                pairs.append((score, i, j))
    return greedy_one_to_one(pairs)


def match_by_text(
    preds: Sequence[str],
    gold: Sequence[Sequence[str]],
    threshold: float = 1.0,
    allowed: Callable[[int, int], bool] | None = None,
) -> list[Match]:
    """Match statements; ``threshold`` 1.0 means normalized-text equality.

    Each gold item offers several texts (annotator restatement, span slices);
    the best similarity counts. ``allowed(pred_index, gold_index)`` can veto a
    pair (the harness uses it to keep matches inside one source).
    """
    pairs = []
    for i, p in enumerate(preds):
        for j, texts in enumerate(gold):
            if allowed is not None and not allowed(i, j):
                continue
            score = max((text_similarity(p, t) for t in texts), default=0.0)
            if score > 0 and score + _EPS >= threshold:
                pairs.append((score, i, j))
    return greedy_one_to_one(pairs)
