"""Builders for the LK-06 chain tests (imported via a sys.path insert; no conftest)."""

from __future__ import annotations

from radius_linking.domain import COMBINED, Link, Reason, SymbolDoc, SymbolTestEdge


def reason(linker: str, score: float = 0.5, kind: str = "x") -> Reason:
    return Reason(linker, kind, f"{linker} evidence", score)


def link(
    criterion: str = "C1",
    symbol: str = "S1",
    *,
    a: float = 0.8,
    explicit: float | None = None,
    linkers: tuple[str, ...] | None = None,
    main: str = COMBINED,
    combined: bool = True,
) -> Link:
    """A criterion -> symbol link whose evidence names ``linkers`` (and an explicit reason)."""

    if linkers is None:
        linkers = () if explicit is not None else ("lexical",)
    evidence = [reason(name, 0.5) for name in linkers if name != "explicit"]
    if explicit is not None:
        evidence.append(reason("explicit", explicit))
    linker = COMBINED if combined else main
    return Link(criterion, symbol, linker, a, tuple(evidence))


def edge(
    symbol: str = "S1",
    test: str = "T1",
    *,
    b: float = 0.9,
    kind: str = "direct_call",
    low: bool = False,
    comps: tuple[tuple[str, float], ...] = (),
) -> SymbolTestEdge:
    return SymbolTestEdge(
        symbol, test, b, kind=kind, low_confidence=low, components=comps
    )


def symdoc(
    symbol_id: str = "S1", *, change: str = "modified_body", behavioral: bool = True
) -> SymbolDoc:
    return SymbolDoc(
        symbol_id=symbol_id,
        path="src/a.py",
        qualified_name=symbol_id,
        change_kind=change,
        is_behavioral=behavioral,
    )
