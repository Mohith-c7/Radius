"""Criterion -> symbol linking pipeline (LK-02).

``link_criteria`` runs independent linkers over the candidate symbols, combines
their scores per (criterion, symbol), optionally lets a :class:`Reranker`
re-order the top candidates, and returns a deterministic :class:`LinkSet`.

Guarantees (tested): only symbols in the input set ever appear in a link; a
failing linker or reranker is skipped with a diagnostic instead of raising;
the same inputs give a byte-identical ``LinkSet.to_json()``; and no link is
produced without at least one :class:`Reason`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from radius_linking.application.combine import (
    COMBINER_VERSION,
    CombineConfig,
    combine_scores,
)
from radius_linking.domain import (
    COMBINED,
    LINKER_RERANK,
    CriterionInput,
    Link,
    LinkContext,
    LinkerPort,
    LinkSet,
    NeighborPort,
    PriorPort,
    Reason,
    RerankCandidate,
    Reranker,
    SymbolDoc,
    clamp01,
    link_sort_key,
)


@dataclass(frozen=True)
class LinkingConfig:
    combine: CombineConfig = field(default_factory=CombineConfig)
    exclude_test_symbols: bool = True
    max_symbols: int = 5000
    rerank_top_n: int = 5
    rerank_weight: float = 0.35

    def __post_init__(self) -> None:
        if self.max_symbols < 1 or self.rerank_top_n < 1:
            raise ValueError("max_symbols and rerank_top_n must be >= 1")
        if not 0.0 <= self.rerank_weight <= 1.0:
            raise ValueError("rerank_weight must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "combine": self.combine.to_dict(),
            "exclude_test_symbols": self.exclude_test_symbols,
            "max_symbols": self.max_symbols,
            "rerank_top_n": self.rerank_top_n,
            "rerank_weight": self.rerank_weight,
        }


def select_candidates(
    symbols: Sequence[SymbolDoc], config: LinkingConfig
) -> tuple[list[SymbolDoc], list[str]]:
    """Deduplicate by id, drop test symbols, bound the size. Returns (candidates, diagnostics)."""

    diags: list[str] = []
    seen: dict[str, SymbolDoc] = {}
    for s in symbols:
        seen.setdefault(s.symbol_id, s)
    ordered = sorted(
        seen.values(), key=lambda s: (s.path, s.qualified_name, s.symbol_id)
    )
    if config.exclude_test_symbols:
        kept = [s for s in ordered if not s.is_test]
        if len(kept) != len(ordered):
            diags.append(f"excluded_test_symbols:{len(ordered) - len(kept)}")
        ordered = kept
    if len(ordered) > config.max_symbols:
        # Keep behavioural changes first, then the deterministic path order.
        ordered = sorted(
            ordered,
            key=lambda s: (not s.is_behavioral, s.path, s.qualified_name, s.symbol_id),
        )[: config.max_symbols]
        ordered.sort(key=lambda s: (s.path, s.qualified_name, s.symbol_id))
        diags.append(f"truncated_symbols:{config.max_symbols}")
    return ordered, diags


def _rank(links: list[Link], k: int) -> list[Link]:
    links = sorted(links, key=lambda x: (-round(x.score, 6), x.symbol_id))[:k]
    return [x.with_rank(i) for i, x in enumerate(links, start=1)]


def link_criteria(
    criteria: Sequence[CriterionInput],
    symbols: Sequence[SymbolDoc],
    *,
    linkers: Sequence[LinkerPort],
    prior: PriorPort | None = None,
    config: LinkingConfig | None = None,
    neighbors: NeighborPort | None = None,
    reranker: Reranker | None = None,
    snapshot_id: str = "",
    changeset_ref: str = "",
    on_error: Callable[[str, Exception], None] | None = None,
) -> LinkSet:
    cfg = config or LinkingConfig()
    cand, diags = select_candidates(symbols, cfg)
    by_id = {s.symbol_id: s for s in cand}
    crit_ids = sorted({c.criterion_id for c in criteria})
    uniq: dict[str, CriterionInput] = {}
    for c in criteria:
        uniq.setdefault(c.criterion_id, c)
    ordered_criteria = [uniq[i] for i in crit_ids]
    for c in ordered_criteria:
        if not c.text.strip() and not (c.paths or c.tests):
            diags.append(f"empty_criterion:{c.criterion_id}")

    context = LinkContext(neighbors=neighbors)
    versions: dict[str, str] = {"combiner": COMBINER_VERSION}
    # (criterion, symbol) -> linker -> Link
    cells: dict[tuple[str, str], dict[str, Link]] = defaultdict(dict)
    per_linker: list[Link] = []
    for linker in linkers:
        versions[linker.name] = linker.version
        try:
            produced = linker.link(ordered_criteria, cand, context) if cand else []
        except Exception as exc:  # a broken linker must not sink the others
            diags.append(f"linker_failed:{linker.name}:{type(exc).__name__}")
            if on_error:
                on_error(linker.name, exc)
            continue
        for link in produced:
            if link.symbol_id not in by_id or link.criterion_id not in uniq:
                diags.append(f"dropped_foreign_link:{linker.name}")
                continue
            if link.score <= 0 or not link.evidence:
                continue
            prev = cells[(link.criterion_id, link.symbol_id)].get(linker.name)
            if prev is None or link.score > prev.score:
                cells[(link.criterion_id, link.symbol_id)][linker.name] = link

    if prior is not None:
        versions[prior.name] = prior.version

    combined: dict[str, list[Link]] = defaultdict(list)
    for (cid, sid), parts in sorted(cells.items()):
        sym = by_id[sid]
        p_value, p_reason = prior.prior(sym) if prior is not None else (1.0, None)
        score = combine_scores(
            {n: x.score for n, x in parts.items()}, p_value, cfg.combine
        )
        if score < cfg.combine.min_score:
            continue
        reasons: list[Reason] = [r for x in parts.values() for r in x.evidence]
        reasons.sort(key=lambda r: (-r.score, r.linker, r.kind, r.detail))
        if p_reason is not None:
            reasons.append(p_reason)
        combined[cid].append(Link(cid, sid, COMBINED, clamp01(score), tuple(reasons)))
        per_linker.extend(parts.values())
        if prior is not None and p_reason is not None:
            per_linker.append(Link(cid, sid, prior.name, p_value, (p_reason,)))

    rerank_links: list[Link] = []
    if reranker is not None:
        versions[f"reranker:{reranker.name}"] = reranker.version
        for c in ordered_criteria:
            top = _rank(combined.get(c.criterion_id, []), cfg.rerank_top_n)
            if not top:
                continue
            cands = [
                RerankCandidate(
                    x.symbol_id,
                    by_id[x.symbol_id].path,
                    by_id[x.symbol_id].qualified_name,
                    by_id[x.symbol_id].kind,
                    by_id[x.symbol_id].change_kind,
                    x.score,
                )
                for x in top
            ]
            try:
                result = reranker.rerank(c, cands)
            except Exception as exc:
                diags.append(f"reranker_failed:{reranker.name}:{type(exc).__name__}")
                if on_error:
                    on_error(reranker.name, exc)
                continue
            diags.extend(f"rerank:{d}" for d in result.diagnostics)
            allowed = {x.symbol_id for x in top}
            updated: dict[str, Link] = {}
            for sid, adj in sorted(result.adjustments.items()):
                if sid not in allowed:
                    diags.append("rerank_ignored_non_candidate")
                    continue
                old = next(x for x in combined[c.criterion_id] if x.symbol_id == sid)
                try:
                    llm = clamp01(float(adj.score))
                except (TypeError, ValueError):
                    diags.append("rerank_ignored_bad_score")
                    continue
                new = clamp01(
                    (1.0 - cfg.rerank_weight) * old.score + cfg.rerank_weight * llm
                )
                why = Reason(
                    LINKER_RERANK, "rerank", str(adj.reason)[:240], round(llm, 6)
                )
                updated[sid] = Link(
                    c.criterion_id, sid, COMBINED, new, (*old.evidence, why)
                )
                rerank_links.append(
                    Link(c.criterion_id, sid, LINKER_RERANK, llm, (why,))
                )
            combined[c.criterion_id] = [
                updated.get(x.symbol_id, x) for x in combined[c.criterion_id]
            ]

    final: list[Link] = []
    for cid in crit_ids:
        final.extend(_rank(combined.get(cid, []), cfg.combine.top_k))
    ranked_linker: list[Link] = []
    grouped: dict[tuple[str, str], list[Link]] = defaultdict(list)
    for x in [*per_linker, *rerank_links]:
        grouped[(x.criterion_id, x.linker)].append(x)
    for key in sorted(grouped):
        ranked_linker.extend(
            _rank(grouped[key], max(cfg.combine.top_k * 3, cfg.combine.top_k))
        )
    ranked_linker.sort(key=lambda x: (*link_sort_key(x)[:2], x.rank, x.symbol_id))

    return LinkSet(
        snapshot_id=snapshot_id,
        changeset_ref=changeset_ref,
        links=tuple(final),
        by_linker=tuple(ranked_linker),
        algo_versions=versions,
        config=cfg.to_dict(),
        diagnostics=tuple(dict.fromkeys(diags)),
    )
