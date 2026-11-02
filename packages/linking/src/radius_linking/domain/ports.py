"""Ports of the linking domain (LK-02)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from radius_linking.domain.model import CriterionInput, Link, Reason, SymbolDoc


class NeighborPort(Protocol):
    """Call-graph proximity among symbols, by ``SymbolDoc.ref``.

    ``neighbors(ref)`` returns ``{other_ref: hops}`` (hops >= 1, either call
    direction) for symbols reachable from ``ref`` within the index's depth.
    """

    def neighbors(self, ref: str) -> Mapping[str, int]: ...


@dataclass(frozen=True)
class LinkContext:
    """Shared, read-only inputs of one linking run."""

    neighbors: NeighborPort | None = None
    options: Mapping[str, float] = field(default_factory=dict)


class LinkerPort(Protocol):
    """One independent, versioned, explainable criterion -> symbol linker.

    ``link`` must be a pure function of its arguments (no clock, no network,
    no randomness) and return only edges with ``score > 0``, each carrying at
    least one :class:`Reason`, for symbols that are in ``symbols``.
    """

    name: str
    version: str

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]: ...


class PriorPort(Protocol):
    """Per-symbol prior (for example the change-kind prior) used as a score modifier."""

    name: str
    version: str

    def prior(self, symbol: SymbolDoc) -> tuple[float, Reason]: ...


@dataclass(frozen=True)
class RerankCandidate:
    """A deterministic candidate offered to a reranker (code-free metadata only)."""

    symbol_id: str
    path: str
    qualified_name: str
    kind: str
    change_kind: str
    score: float


@dataclass(frozen=True)
class RerankAdjustment:
    score: float
    reason: str


@dataclass(frozen=True)
class RerankResult:
    """``adjustments`` by symbol id. Anything not a candidate is ignored by the caller."""

    adjustments: Mapping[str, RerankAdjustment] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    version: str = ""


class Reranker(Protocol):
    """Optional re-ranker/explainer of already-found candidates.

    It may only judge the candidates it is given; the pipeline discards any
    symbol that was not a candidate, so a reranker can never add a link.
    """

    name: str
    version: str

    def rerank(
        self, criterion: CriterionInput, candidates: Sequence[RerankCandidate]
    ) -> RerankResult: ...
