"""Evaluation hooks for symbol-to-test links (LK-03).

Pure metric code; the fixture driver lives in ``scripts/test_link_eval.py``.
Numbers produced on the in-repo fixtures are *fixture sanity checks, not a
research result* (LK-07 owns the real evaluation on the gold set).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from radius_testing.linking.model import LinkSet, normalize_test_id

LABEL = "fixture sanity, not a research result"


@dataclass(frozen=True, slots=True)
class Prf:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def prf(selected: Collection[str], truth: Collection[str]) -> Prf:
    """Precision/recall of a selected test set against a ground-truth set.

    Empty selection and empty truth is a perfect score (nothing to find, nothing
    wrongly selected); an empty selection against a non-empty truth has recall 0.
    """

    sel = {normalize_test_id(t) for t in selected}
    gt = {normalize_test_id(t) for t in truth}
    tp, fp, fn = len(sel & gt), len(sel - gt), len(gt - sel)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return Prf(round(precision, 4), round(recall, 4), round(f1, 4), tp, fp, fn)


def select_tests(links: LinkSet, symbols: Iterable[str], *, min_score: float) -> set[str]:
    """Tests that a link with ``score >= min_score`` ties to any of ``symbols``."""

    wanted = set(symbols)
    return {lk.test_id for lk in links.links if lk.symbol_id in wanted and lk.score >= min_score}


def evaluate_linksets(
    linksets: Mapping[str, LinkSet],
    symbols: Iterable[str],
    truth: Collection[str],
    *,
    min_score: float = 0.3,
) -> dict[str, Prf]:
    """Score each named link set (single linkers, combinations) against ``truth``."""

    syms = list(symbols)
    return {name: prf(select_tests(ls, syms, min_score=min_score), truth) for name, ls in linksets.items()}


def ablation(
    static: LinkSet | None,
    naming: LinkSet | None,
    dynamic: LinkSet | None,
    symbols: Iterable[str],
    truth: Collection[str],
    *,
    min_score: float = 0.3,
) -> dict[str, Prf]:
    """Leave-one-linker-out and single-linker scores for the combiner."""

    from radius_testing.linking.combine import combine_links

    syms = list(symbols)
    variants: dict[str, LinkSet] = {}
    parts = {"static": static, "naming": naming, "dynamic": dynamic}
    for name, ls in parts.items():
        if ls is not None:
            variants[f"only:{name}"] = ls
    if all(v is not None for v in parts.values()):
        variants["all"] = combine_links(static, naming, dynamic)
        for name in parts:
            rest = {k: v for k, v in parts.items() if k != name}
            variants[f"without:{name}"] = combine_links(**rest)
    elif static is not None and naming is not None:
        variants["static+naming"] = combine_links(static, naming)
    return evaluate_linksets(variants, syms, truth, min_score=min_score)
