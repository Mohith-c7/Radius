"""Evaluation hooks for criterion -> symbol linking (RQ1; consumed by LK-07).

Gold links use the same shape as ``benchmarks/fixtures/intent/*/expected.json``:
``{"links": [{"criterion": "C1", "symbol": "src/pricing.py::apply_discount"}, ...]}``.
Symbols are compared by ``SymbolDoc.ref`` (``path::qualified_name``).

Metrics per set of criteria that have at least one gold symbol:
``top1`` / ``top3`` = share whose first / first-three ranked symbols contain a
gold symbol; ``mrr`` = mean of ``1 / rank`` of the first gold symbol (0 when no
gold symbol is ranked). A criterion with no prediction counts as a miss.
These are measurement functions only; they report nothing about quality by
themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_linking.domain import COMBINED, LinkSet, SymbolDoc


@dataclass(frozen=True)
class RankMetrics:
    n: int
    top1: float
    top3: float
    mrr: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "top1": round(self.top1, 4),
            "top3": round(self.top3, 4),
            "mrr": round(self.mrr, 4),
        }


def gold_from_expected(expected: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """``expected.json`` -> ``{criterion_id: {symbol_ref}}`` (uses the ``links`` list)."""

    out: dict[str, set[str]] = {}
    for link in expected.get("links", []):
        out.setdefault(link["criterion"], set()).add(link["symbol"])
    return {k: frozenset(v) for k, v in sorted(out.items())}


def evaluate_rankings(
    rankings: Mapping[str, Sequence[str]], gold: Mapping[str, Collection[str]]
) -> RankMetrics:
    """Top-1 / Top-3 / MRR of ``rankings`` (criterion -> ranked symbol refs) against ``gold``."""

    scored = [(cid, set(g)) for cid, g in sorted(gold.items()) if g]
    if not scored:
        return RankMetrics(0, 0.0, 0.0, 0.0)
    top1 = top3 = 0
    rr = 0.0
    for cid, g in scored:
        ranked = list(rankings.get(cid, ()))
        first = next((i for i, ref in enumerate(ranked, start=1) if ref in g), None)
        if first is None:
            continue
        top1 += first <= 1
        top3 += first <= 3
        rr += 1.0 / first
    n = len(scored)
    return RankMetrics(n, top1 / n, top3 / n, rr / n)


def rankings_from_linkset(
    linkset: LinkSet,
    symbols: Iterable[SymbolDoc],
    *,
    linker: str = COMBINED,
    label_of: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Ranked symbol refs per criterion for one linker (or ``combined``).

    ``label_of`` maps criterion ids to the gold labels (for example hash ids to
    ``C1``); default identity.
    """

    ref_of = {s.symbol_id: s.ref for s in symbols}
    cids = sorted({x.criterion_id for x in (*linkset.links, *linkset.by_linker)})
    out: dict[str, list[str]] = {}
    for cid in cids:
        label = (label_of or {}).get(cid, cid)
        out[label] = [ref_of.get(sid, sid) for sid in linkset.ranking(cid, linker)]
    return out


def evaluate_linkset(
    linkset: LinkSet,
    symbols: Sequence[SymbolDoc],
    gold: Mapping[str, Collection[str]],
    *,
    label_of: Mapping[str, str] | None = None,
    linker_names: Sequence[str] = (),
) -> dict[str, RankMetrics]:
    """Metrics for the combined ranking and for every individual linker.

    Linkers that produced nothing report zeros when named in ``linker_names``.
    """

    names = sorted({x.linker for x in linkset.by_linker} | set(linker_names))
    out = {
        COMBINED: evaluate_rankings(
            rankings_from_linkset(linkset, symbols, label_of=label_of), gold
        )
    }
    for name in names:
        out[name] = evaluate_rankings(
            rankings_from_linkset(linkset, symbols, linker=name, label_of=label_of),
            gold,
        )
    return out


def ablation(
    run: Callable[[frozenset[str]], LinkSet],
    linker_names: Sequence[str],
    symbols: Sequence[SymbolDoc],
    gold: Mapping[str, Collection[str]],
    *,
    label_of: Mapping[str, str] | None = None,
) -> dict[str, RankMetrics]:
    """Per-linker ablation of the *combined* ranking.

    ``run(enabled)`` must link with exactly the linkers named in ``enabled``.
    Returns ``all``, ``without:<name>`` and ``only:<name>`` entries.
    """

    names = frozenset(linker_names)

    def metrics(enabled: frozenset[str]) -> RankMetrics:
        ls = run(enabled)
        return evaluate_rankings(
            rankings_from_linkset(ls, symbols, label_of=label_of), gold
        )

    out = {"all": metrics(names)}
    for name in sorted(names):
        out[f"without:{name}"] = metrics(names - {name})
    for name in sorted(names):
        out[f"only:{name}"] = metrics(frozenset({name}))
    return out


def links_as_expected(
    linkset: LinkSet,
    symbols: Sequence[SymbolDoc],
    *,
    label_of: Mapping[str, str] | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Top-``k`` predictions in the ``expected.json`` ``links`` style (plus score and rank)."""

    ref_of = {s.symbol_id: s.ref for s in symbols}
    out: list[dict[str, Any]] = []
    for x in linkset.links:
        if x.rank <= k:
            out.append(
                {
                    "criterion": (label_of or {}).get(x.criterion_id, x.criterion_id),
                    "symbol": ref_of.get(x.symbol_id, x.symbol_id),
                    "rank": x.rank,
                    "score": round(x.score, 4),
                }
            )
    return out
