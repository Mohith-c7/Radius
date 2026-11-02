"""Combine static, naming and dynamic links per (symbol, test) (LK-03).

Rule (``link-combine-v1``), written so that adding evidence never lowers a score
(every step is ``max`` or a noisy-or of non-negative terms):

1. ``sn`` -- the non-dynamic score
   * static only: ``s``  (cap 0.90)
   * naming only: ``min(n, 0.50)``               (a convention alone is weak)
   * both agree:  ``max(1 - (1 - s) * (1 - 0.5 n'), min(n, 0.5))`` with ``n' = n`` if
     ``n >= 0.30`` else 0 (file-level naming is not independent evidence)  (boost, cap 0.90;
     the max keeps the rule monotone when a weak static link joins a naming link)
2. dynamic evidence dominates: with a dynamic score ``d`` (0..1),
   ``dyn = 0.92 + 0.07 d`` and ``final = max(sn, dyn)``; static/naming agreement
   adds a boost ``1 - (1 - final) * (1 - 0.3 sn)`` (cap 0.99).
3. Without dynamic evidence the score never exceeds 0.90; a dynamic link is
   always >= 0.92, so a measured execution outranks any static guess.

Per-linker scores, kinds and algo versions are preserved in ``components`` and
the evidence lists are concatenated (dynamic first), de-duplicated and bounded.
Absence of a dynamic link never lowers a score: the dynamic run may have been
partial (timeout, failed test), so it cannot refute a static link.
"""

from __future__ import annotations

from collections.abc import Iterable

from radius_testing.linking.model import (
    COMBINE_ALGO_VERSION,
    LINKER_COMBINED,
    LINKER_DYNAMIC,
    LINKER_NAMING,
    LINKER_STATIC,
    MAX_EVIDENCE_PER_LINK,
    LinkComponent,
    LinkKind,
    LinkSet,
    SymbolTestLink,
    clamp01,
)

NAMING_ALONE_CAP = 0.50
NAMING_BOOST_WEIGHT = 0.5
NAMING_BOOST_MIN = 0.30  # only function/class-level naming evidence counts as agreement
STATIC_CAP = 0.90
DYNAMIC_FLOOR = 0.92
DYNAMIC_SPAN = 0.07
AGREEMENT_WEIGHT = 0.3
DYNAMIC_CAP = 0.99


def combined_score(static: float = 0.0, naming: float = 0.0, dynamic: float | None = None) -> float:
    """Pure scoring rule; ``dynamic=None`` means no dynamic evidence."""

    if static > 0 and naming > 0:
        # file-level naming (< NAMING_BOOST_MIN) is not independent of an import-level static link
        agree = naming if naming >= NAMING_BOOST_MIN else 0.0
        boosted = 1 - (1 - static) * (1 - NAMING_BOOST_WEIGHT * agree)
        sn = min(STATIC_CAP, max(boosted, naming if naming <= NAMING_ALONE_CAP else NAMING_ALONE_CAP))
    elif static > 0:
        sn = min(STATIC_CAP, static)
    else:
        sn = min(NAMING_ALONE_CAP, naming)
    if dynamic is None:
        return clamp01(sn)
    final = max(sn, DYNAMIC_FLOOR + DYNAMIC_SPAN * dynamic)
    final = 1 - (1 - final) * (1 - AGREEMENT_WEIGHT * sn)
    return clamp01(min(DYNAMIC_CAP, final))


def combine_links(
    static: LinkSet | None = None,
    naming: LinkSet | None = None,
    dynamic: LinkSet | None = None,
) -> LinkSet:
    """Merge any subset of the three linkers' outputs; deterministic."""

    groups: dict[tuple[str, str], dict[str, SymbolTestLink]] = {}
    for linker, linkset in (
        (LINKER_STATIC, static),
        (LINKER_NAMING, naming),
        (LINKER_DYNAMIC, dynamic),
    ):
        for link in (linkset.links if linkset else ()):
            slot = groups.setdefault(link.key, {})
            old = slot.get(linker)
            if old is None or link.score > old.score:
                slot[linker] = link
    out = [_merge(key, slot) for key, slot in groups.items()]
    notes: list[str] = []
    for ls in (static, naming, dynamic):
        if ls:
            notes.extend(ls.notes)
    return LinkSet.of(
        out,
        algo_version=COMBINE_ALGO_VERSION,
        notes=notes,
        config={
            "naming_alone_cap": NAMING_ALONE_CAP,
            "static_cap": STATIC_CAP,
            "dynamic_floor": DYNAMIC_FLOOR,
            "inputs": {
                name: ls.algo_version
                for name, ls in ((LINKER_STATIC, static), (LINKER_NAMING, naming), (LINKER_DYNAMIC, dynamic))
                if ls
            },
        },
    )


def _merge(key: tuple[str, str], slot: dict[str, SymbolTestLink]) -> SymbolTestLink:
    st, nm, dy = slot.get(LINKER_STATIC), slot.get(LINKER_NAMING), slot.get(LINKER_DYNAMIC)
    score = combined_score(st.score if st else 0.0, nm.score if nm else 0.0, dy.score if dy else None)
    primary = dy or st or nm
    assert primary is not None
    kind = LinkKind.DYNAMIC_COVERAGE if dy else primary.kind
    evidence = _dedupe(e for link in (dy, st, nm) if link for e in link.evidence)
    components = tuple(
        LinkComponent(link.linker, link.score, link.kind, link.algo_version)
        for link in (st, nm, dy)
        if link is not None
    )
    return SymbolTestLink(
        symbol_id=key[0],
        test_id=key[1],
        linker=LINKER_COMBINED,
        score=score,
        kind=kind,
        evidence=evidence[:MAX_EVIDENCE_PER_LINK],
        depth=st.depth if (st and not dy) else None,
        algo_version=COMBINE_ALGO_VERSION,
        components=components,
        low_confidence=dy is None and nm is None and bool(st and st.low_confidence),
    )


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))
