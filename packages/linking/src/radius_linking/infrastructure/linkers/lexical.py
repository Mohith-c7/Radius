"""Lexical linker: BM25 between criterion text and symbol documents.

Each symbol document is a bag of stemmed terms from weighted fields (BM25F-lite:
a field's terms are counted ``weight`` times). Defaults: qualified name x3,
docstring x2, decorators x2, file path x1, signature x1, comments x1,
identifiers in the body x1, string literals x1. Query terms come from the
criterion text (weight 1.0) and the testability rationale (weight 0.5; a term
already in the text keeps weight 1.0).

Score normalisation (documented, not a probability): with ``raw`` the weighted
BM25 sum and ``ref = sum(w_t * idf_t * (k1 + 1))`` over the query terms present in
the corpus (the asymptotic maximum of each term's BM25 contribution),
``abs = min(1, raw / ref)`` is the share of attainable BM25 mass the symbol collects;
``coverage`` is the weight share of query terms found in the corpus;
``score = cap * abs * (0.5 + 0.5 * coverage)`` with ``cap = 0.9``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from radius_linking.domain import (
    LINKER_LEXICAL,
    CriterionInput,
    Link,
    LinkContext,
    SymbolDoc,
)
from radius_linking.domain.bm25 import BM25Index
from radius_linking.domain.text import code_terms, name_terms, terms
from radius_linking.infrastructure.linkers.common import reason, sort_reasons

VERSION = "lexical-bm25-v1"
PATH_STOPWORDS = frozenset(
    "src lib libs app apps pkg packages package py pyi js jsx ts tsx mjs go java rb rs init index main".split()
)


@dataclass(frozen=True)
class LexicalConfig:
    k1: float = 1.2
    b: float = 0.75
    cap: float = 0.9
    rationale_weight: float = 0.5
    max_reasons: int = 5
    field_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "name": 3.0,
            "docstring": 2.0,
            "decorators": 2.0,
            "path": 1.0,
            "signature": 1.0,
            "comments": 1.0,
            "identifiers": 1.0,
            "literals": 1.0,
        }
    )


def symbol_fields(sym: SymbolDoc) -> dict[str, list[str]]:
    """Field name -> stemmed terms for one symbol."""

    path_terms = [
        t
        for t in terms(sym.path.replace("/", " ").replace(".", " "), do_stem=True)
        if t not in PATH_STOPWORDS
    ]
    return {
        "name": name_terms(sym.qualified_name),
        "path": path_terms,
        "docstring": terms(sym.docstring),
        "signature": code_terms(sym.signature),
        "decorators": code_terms(" ".join(sym.decorators)),
        "comments": terms(" ".join(sym.comments)),
        "identifiers": code_terms(" ".join(sym.identifiers)),
        "literals": terms(" ".join(sym.literals)),
    }


def symbol_tf(sym: SymbolDoc, weights: Mapping[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for fname, toks in symbol_fields(sym).items():
        w = weights.get(fname, 1.0)
        for t in toks:
            tf[t] = tf.get(t, 0.0) + w
    return tf


def query_weights(
    criterion: CriterionInput, rationale_weight: float
) -> dict[str, float]:
    q: dict[str, float] = {}
    for t in terms(criterion.text):
        q[t] = 1.0
    if criterion.rationale:
        for t in terms(criterion.rationale):
            q.setdefault(t, rationale_weight)
    return dict(sorted(q.items()))


class LexicalLinker:
    name = LINKER_LEXICAL
    version = VERSION

    def __init__(self, config: LexicalConfig | None = None) -> None:
        self.config = config or LexicalConfig()

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]:
        cfg = self.config
        if not symbols:
            return []
        by_id = {s.symbol_id: s for s in symbols}
        index = BM25Index(
            {s.symbol_id: symbol_tf(s, cfg.field_weights) for s in symbols},
            k1=cfg.k1,
            b=cfg.b,
        )
        vocab = index.vocabulary()
        links: list[Link] = []
        for crit in criteria:
            q = query_weights(crit, cfg.rationale_weight)
            if not q:
                continue
            known = {t: w for t, w in q.items() if t in vocab}
            if not known:
                continue
            ref = sum(w * index.max_term_score(t) for t, w in known.items())
            coverage = sum(known.values()) / sum(q.values())
            if ref <= 0:
                continue
            qterms = list(known)
            for symbol_id in sorted(index.scores(qterms)):
                parts = index.term_scores(qterms, symbol_id)
                raw = sum(known[t] * s for t, s in parts.items())
                score = cfg.cap * min(1.0, raw / ref) * (0.5 + 0.5 * coverage)
                if score <= 0:
                    continue
                top = sorted(
                    parts.items(), key=lambda kv: (-known[kv[0]] * kv[1], kv[0])
                )
                reasons = [
                    reason(
                        self.name,
                        "bm25_term",
                        f"term '{t}' bm25={s:.3f}",
                        min(1.0, known[t] * s / ref),
                    )
                    for t, s in top[: cfg.max_reasons]
                ]
                reasons.append(
                    reason(
                        self.name,
                        "bm25_summary",
                        f"matched {len(parts)}/{len(q)} query terms in {by_id[symbol_id].ref}; "
                        f"coverage={coverage:.2f}",
                        score,
                    )
                )
                links.append(
                    Link(
                        crit.criterion_id,
                        symbol_id,
                        self.name,
                        score,
                        sort_reasons(reasons),
                    )
                )
        return links
