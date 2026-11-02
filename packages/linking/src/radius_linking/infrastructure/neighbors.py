"""Call-graph neighbours from the existing graph package (F-08 ``PythonSymbolGraph``).

``PythonSymbolGraph`` is a conservative, name-based reverse-reachability index:
``impact`` from a symbol returns the symbols that can reach it (its callers and
users, transitively, with the BFS parent chain). This adapter turns that into
the ``NeighborPort`` used by the structural linker: for a seed ``ref``
(``path::qualified_name``) it reports callers at ``h`` hops and, by inverting
the same relation among the *focus* symbols, callees at ``h`` hops.

Python only (other languages have no symbol graph yet: no neighbours, never an
error). Over-approximate by design, hence the decay in the structural linker.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from radius_graph.symbol_impact import LineMapping, PythonSymbolGraph


class CallGraphNeighbors:
    def __init__(
        self,
        sources: Mapping[str, str],
        focus: Iterable[str],
        *,
        max_hops: int = 3,
    ) -> None:
        """``sources``: head Python files; ``focus``: candidate refs (callee inversion scope)."""

        self._max_hops = max_hops
        self._graph = PythonSymbolGraph(
            {p: t for p, t in sources.items() if p.endswith(".py")}
        )
        self._focus = sorted(set(focus))
        self._callers: dict[str, dict[str, int]] = {}

    def _callers_of(self, ref: str) -> dict[str, int]:
        if ref in self._callers:
            return self._callers[ref]
        out: dict[str, int] = {}
        path = ref.split("::", 1)[0]
        if ref in {s.id for s in self._graph.symbols(path)}:
            impact = self._graph.impact(
                path,
                LineMapping(symbols=(ref,)),
                dependents_of=lambda _p: frozenset(),
            )
            if impact.is_symbol_level:
                for sid in sorted(impact.impacted_symbols):
                    if sid == ref:
                        continue
                    hops = len(impact.chain(sid)) - 1
                    if 1 <= hops <= self._max_hops:
                        out[sid] = hops
        self._callers[ref] = out
        return out

    def _callees_of(self, ref: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for other in self._focus:
            if other == ref:
                continue
            hops = self._callers_of(other).get(ref)
            if hops is not None:
                out[other] = hops
        return out

    def neighbors(self, ref: str) -> Mapping[str, int]:
        merged = dict(self._callees_of(ref))
        for other, hops in self._callers_of(ref).items():
            merged[other] = min(hops, merged.get(other, hops))
        return dict(sorted(merged.items()))
