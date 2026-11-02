"""Deterministic rerankers for tests and for running without any LLM."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from radius_linking.domain import (
    CriterionInput,
    RerankAdjustment,
    RerankCandidate,
    RerankResult,
)
from radius_linking.domain.text import name_terms, terms


class OverlapReranker:
    """Scores a candidate by term overlap between the criterion and its name/path.

    A pure, offline stand-in with the same contract as the LLM reranker: it
    judges only the candidates it is handed.
    """

    name = "overlap-fake"
    version = "overlap-fake-v1"

    def rerank(
        self, criterion: CriterionInput, candidates: Sequence[RerankCandidate]
    ) -> RerankResult:
        want = set(terms(criterion.text))
        out: dict[str, RerankAdjustment] = {}
        for c in candidates:
            have = set(name_terms(c.qualified_name)) | set(
                terms(c.path.replace("/", " "))
            )
            if not want or not have:
                score = 0.0
            else:
                score = len(want & have) / len(want | have)
            out[c.symbol_id] = RerankAdjustment(
                min(1.0, 2.0 * score), f"name/path overlap {len(want & have)} term(s)"
            )
        return RerankResult(out, (), self.version)


class FixedReranker:
    """Returns canned adjustments, including ones for symbols that are not candidates."""

    name = "fixed-fake"
    version = "fixed-fake-v1"

    def __init__(self, adjustments: Mapping[str, tuple[float, str]]) -> None:
        self._adj = dict(adjustments)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def rerank(
        self, criterion: CriterionInput, candidates: Sequence[RerankCandidate]
    ) -> RerankResult:
        self.calls.append(
            (criterion.criterion_id, tuple(c.symbol_id for c in candidates))
        )
        return RerankResult(
            {
                sid: RerankAdjustment(score, why)
                for sid, (score, why) in self._adj.items()
            },
            (),
            self.version,
        )
