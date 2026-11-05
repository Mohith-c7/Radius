"""Precision/recall hook for IN-10 (no CLI, no gold data here).

IN-09's gold set does not exist yet. IN-10 will load gold annotations and call
:func:`score_by_source_kind`; nothing in this module reads files or the clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from radius_intent.domain import IntentSourceKind, normalize_text

from .dedupe import content_tokens, jaccard


@dataclass(frozen=True)
class PrecisionRecall:
    """Counts and derived scores. Empty-vs-empty scores 1.0 by convention."""

    true_positives: int
    predicted: int
    gold: int

    @property
    def precision(self) -> float:
        """Matched predictions / predictions."""
        return (
            self.true_positives / self.predicted
            if self.predicted
            else float(not self.gold)
        )

    @property
    def recall(self) -> float:
        """Matched gold items / gold items."""
        return (
            self.true_positives / self.gold if self.gold else float(not self.predicted)
        )

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def __add__(self, other: PrecisionRecall) -> PrecisionRecall:
        return PrecisionRecall(
            self.true_positives + other.true_positives,
            self.predicted + other.predicted,
            self.gold + other.gold,
        )


@dataclass(frozen=True)
class GoldCase:
    """One gold-set item: a source kind, predicted texts and gold texts."""

    kind: IntentSourceKind
    predicted: Sequence[str]
    gold: Sequence[str]


def score_extraction(
    predicted: Sequence[str],
    gold: Sequence[str],
    *,
    fuzzy_threshold: float | None = None,
) -> PrecisionRecall:
    """Score predicted criterion texts against gold texts.

    Exact mode compares ``normalize_text``; with ``fuzzy_threshold`` a pair also
    matches when the content-token Jaccard is >= the threshold. Matching is
    one-to-one and greedy: best pair first, ties by (predicted, gold) index.
    """
    pred = [normalize_text(t) for t in predicted]
    gold_n = [normalize_text(t) for t in gold]
    pairs: list[tuple[float, int, int]] = []
    ptoks = [content_tokens(t) for t in pred] if fuzzy_threshold else []
    gtoks = [content_tokens(t) for t in gold_n] if fuzzy_threshold else []
    for i, p in enumerate(pred):
        for j, g in enumerate(gold_n):
            if p == g:
                pairs.append((1.0, i, j))
            elif fuzzy_threshold:
                sim = jaccard(ptoks[i], gtoks[j])
                if sim >= fuzzy_threshold:
                    pairs.append((sim, i, j))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_p: set[int] = set()
    used_g: set[int] = set()
    for _, i, j in pairs:
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
    return PrecisionRecall(len(used_p), len(pred), len(gold_n))


def score_by_source_kind(
    cases: Iterable[GoldCase], *, fuzzy_threshold: float | None = None
) -> dict[IntentSourceKind, PrecisionRecall]:
    """Micro-averaged precision/recall per source kind (sorted by kind value)."""
    totals: dict[IntentSourceKind, PrecisionRecall] = {}
    for case in cases:
        score = score_extraction(
            case.predicted, case.gold, fuzzy_threshold=fuzzy_threshold
        )
        totals[case.kind] = totals[case.kind] + score if case.kind in totals else score
    return dict(sorted(totals.items(), key=lambda kv: kv[0].value))
