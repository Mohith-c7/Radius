"""Symbol resolution port (LK-04).

LK-05 / EV-06 plug in the LK-03 results through :class:`SymbolResolver`. Without
one, refs keep their import-qualified names and ``depends_on_changed`` is
``unknown``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from radius_testing.linking.model import LinkTarget, SymbolTestLink


class SymbolResolver(Protocol):
    """Map a name used in a test to symbol ids."""

    def resolve(self, test_id: str, name: str, qualified: str | None, path: str) -> tuple[str, ...]:
        """Return symbol ids for ``name`` (as written) / ``qualified`` (import-qualified)."""


def _module_dotted(path: str) -> str:
    stem = path.rsplit(".", 1)[0] if "." in path.rsplit("/", 1)[-1] else path
    parts = [p for p in stem.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class LinkTargetResolver:
    """Resolve import-qualified names against LK-01/LK-03 ``LinkTarget``s.

    ``pkg.mod.f`` matches a target whose dotted path + qualified name ends with it
    (so ``src/`` style prefixes do not matter). TS/JS refs are ``path#member``.
    """

    def __init__(self, targets: Iterable[LinkTarget]) -> None:
        self._full: list[tuple[str, str]] = []
        self._js: dict[tuple[str, str], str] = {}
        for t in targets:
            if t.language == "python":
                self._full.append((_module_dotted(t.path) + "." + t.entity_name, t.symbol_id))
            else:
                self._js[(t.path, t.entity_name.split(".")[-1])] = t.symbol_id
                self._js[(t.path, t.entity_name)] = t.symbol_id
        self._full.sort()

    def resolve(self, test_id: str, name: str, qualified: str | None, path: str) -> tuple[str, ...]:
        if not qualified:
            return ()
        if "#" in qualified:
            p, member = qualified.split("#", 1)
            hit = self._js.get((p, member))
            return (hit,) if hit else ()
        q = qualified.lstrip(".")
        return tuple(sorted({sid for full, sid in self._full if full == q or full.endswith("." + q)}))


def linked_symbols_by_test(links: Iterable[SymbolTestLink] | None) -> dict[str, frozenset[str]] | None:
    """``test_id -> {symbol_id}`` from LK-03 links (``None`` when no links given)."""

    if links is None:
        return None
    # accept a LinkSet (has ``.links``) as well as a plain iterable
    items = getattr(links, "links", links)
    out: dict[str, set[str]] = {}
    for link in items:
        out.setdefault(link.test_id, set()).add(link.symbol_id)
    return {k: frozenset(v) for k, v in out.items()}

