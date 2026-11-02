"""Okapi BM25 in pure Python (no dependencies).

``idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5))`` (the non-negative Lucene form),
``score(q, d) = sum_{t in set(q)} idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * |d| / avgdl))``.
Term frequencies may be fractional so callers can weight fields (BM25F-lite:
a field's tokens are counted ``weight`` times). Iteration is over sorted keys,
so results are bit-for-bit reproducible.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence


class BM25Index:
    def __init__(
        self,
        docs: Mapping[str, Mapping[str, float]],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("require k1 >= 0 and 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self._tf: dict[str, dict[str, float]] = {
            doc_id: {t: float(f) for t, f in sorted(tf.items()) if f > 0}
            for doc_id, tf in sorted(docs.items())
        }
        self.n_docs = len(self._tf)
        self._len = {d: sum(tf.values()) for d, tf in self._tf.items()}
        total = sum(self._len.values())
        self.avgdl = total / self.n_docs if self.n_docs else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf.values():
            df.update(tf.keys())
        self._df = df
        self._postings: dict[str, list[str]] = {}
        for doc_id, tf in self._tf.items():
            for term in tf:
                self._postings.setdefault(term, []).append(doc_id)

    @classmethod
    def from_tokens(cls, docs: Mapping[str, Sequence[str]], **kw: float) -> BM25Index:
        return cls({d: Counter(toks) for d, toks in docs.items()}, **kw)

    def vocabulary(self) -> frozenset[str]:
        return frozenset(self._df)

    def df(self, term: str) -> int:
        return self._df.get(term, 0)

    def idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def _term_score(self, term: str, doc_id: str) -> float:
        tf = self._tf[doc_id].get(term, 0.0)
        if tf <= 0:
            return 0.0
        dl = self._len[doc_id]
        norm = 1.0 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0.0)
        return self.idf(term) * tf * (self.k1 + 1.0) / (tf + self.k1 * norm)

    def term_scores(self, query: Sequence[str], doc_id: str) -> dict[str, float]:
        """Per-term contributions of ``doc_id`` for the unique query terms (explanations)."""

        return {
            t: s for t in sorted(set(query)) if (s := self._term_score(t, doc_id)) > 0.0
        }

    def score(self, query: Sequence[str], doc_id: str) -> float:
        return sum(self.term_scores(query, doc_id).values())

    def scores(self, query: Sequence[str]) -> dict[str, float]:
        """Scores of every document sharing at least one term with ``query``."""

        out: dict[str, float] = {}
        for term in sorted(set(query)):
            for doc_id in self._postings.get(term, ()):
                out[doc_id] = out.get(doc_id, 0.0) + self._term_score(term, doc_id)
        return dict(sorted(out.items()))

    def max_term_score(self, term: str) -> float:
        """Asymptotic ceiling ``idf * (k1 + 1)`` of one term's contribution."""

        return self.idf(term) * (self.k1 + 1.0)
