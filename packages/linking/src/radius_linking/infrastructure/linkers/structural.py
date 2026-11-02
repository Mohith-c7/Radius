"""Structural-proximity linker.

Seeds are the symbols an explicit hint points at with score >= ``seed_min``
(see :mod:`explicit`). Every other candidate is scored by how close it is:

* same file as a seed: ``0.6``
* same directory: ``0.35``; parent directory: ``0.2``
* call-graph neighbour at ``h`` hops (callers or callees, from the
  ``NeighborPort``): ``0.7 * 0.6 ** (h - 1)``

and the score is ``seed_score * proximity`` (max over seeds), capped at
``cap = 0.7``. Seeds themselves are left to the explicit linker. Without hints
there are no seeds and this linker is silent (it never guesses seeds).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from radius_linking.domain import (
    LINKER_STRUCTURAL,
    CriterionInput,
    Link,
    LinkContext,
    Reason,
    SymbolDoc,
)
from radius_linking.infrastructure.linkers.common import (
    reason,
    sort_reasons,
    symbol_dir,
)
from radius_linking.infrastructure.linkers.explicit import match_hints

VERSION = "structural-v1"


@dataclass(frozen=True)
class StructuralConfig:
    seed_min: float = 0.6
    same_file: float = 0.6
    same_dir: float = 0.35
    parent_dir: float = 0.2
    graph_base: float = 0.7
    graph_decay: float = 0.6
    max_hops: int = 3
    cap: float = 0.7


def _parent(d: str) -> str:
    return d.rsplit("/", 1)[0] if "/" in d else "."


def _offer(
    linker: str,
    best: dict[str, list[tuple[float, Reason]]],
    raw: float,
    sym: SymbolDoc,
    kind: str,
    detail: str,
    cap: float,
) -> None:
    score = min(cap, raw)
    if score > 0:
        best.setdefault(sym.symbol_id, []).append(
            (score, reason(linker, kind, detail, score))
        )


class StructuralLinker:
    name = LINKER_STRUCTURAL
    version = VERSION

    def __init__(self, config: StructuralConfig | None = None) -> None:
        self.config = config or StructuralConfig()

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]:
        cfg = self.config
        links: list[Link] = []
        for crit in criteria:
            hints = match_hints(crit, symbols)
            seeds = {
                sid: max(r.score for r in rs)
                for sid, rs in hints.items()
                if max(r.score for r in rs) >= cfg.seed_min
            }
            if not seeds:
                continue
            seed_syms = [s for s in symbols if s.symbol_id in seeds]
            best: dict[str, list[tuple[float, Reason]]] = {}

            for seed in seed_syms:
                weight = seeds[seed.symbol_id]
                sdir = symbol_dir(seed)
                graph = (
                    context.neighbors.neighbors(seed.ref)
                    if context.neighbors is not None
                    else {}
                )
                for sym in symbols:
                    if sym.symbol_id in seeds:
                        continue
                    if sym.path == seed.path:
                        _offer(
                            self.name,
                            best,
                            weight * cfg.same_file,
                            sym,
                            "same_file",
                            f"same file as {seed.ref}",
                            cfg.cap,
                        )
                    elif symbol_dir(sym) == sdir:
                        _offer(
                            self.name,
                            best,
                            weight * cfg.same_dir,
                            sym,
                            "same_dir",
                            f"same directory as {seed.ref}",
                            cfg.cap,
                        )
                    elif (
                        symbol_dir(sym) == _parent(sdir)
                        or _parent(symbol_dir(sym)) == sdir
                    ):
                        _offer(
                            self.name,
                            best,
                            weight * cfg.parent_dir,
                            sym,
                            "near_dir",
                            f"adjacent directory to {seed.ref}",
                            cfg.cap,
                        )
                    hops = graph.get(sym.ref)
                    if hops is not None and 1 <= hops <= cfg.max_hops:
                        prox = cfg.graph_base * cfg.graph_decay ** (hops - 1)
                        _offer(
                            self.name,
                            best,
                            weight * prox,
                            sym,
                            "call_graph",
                            f"{hops} call hop(s) from {seed.ref}",
                            cfg.cap,
                        )
            for symbol_id in sorted(best):
                options = best[symbol_id]
                score = max(s for s, _ in options)
                links.append(
                    Link(
                        crit.criterion_id,
                        symbol_id,
                        self.name,
                        score,
                        sort_reasons([r for _, r in options]),
                    )
                )
        return links
