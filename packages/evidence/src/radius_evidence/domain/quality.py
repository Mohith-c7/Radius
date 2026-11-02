"""Evidence quality contract (design 3.5). The combiner is EV-08's."""

from __future__ import annotations

from dataclasses import dataclass

from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import EVIDENCE_QUALITY_VERSION


@dataclass(frozen=True, slots=True)
class ChainRef(Serializable):
    """The criterion -> symbol -> test path an item was credited through."""

    symbol_id: str
    test_id: str
    l_cs: float = 0.0
    l_st: float = 0.0
    r_ct: float = 0.0


@dataclass(frozen=True, slots=True)
class EvidenceQuality(Serializable):
    """One row per (evidence, criterion), including unusable ones (for ablations).

    ``status`` is ``counted`` or ``gated:<reason>``. ``l`` is the design symbol
    for link strength ``l_cs * l_st * r_ct``.
    """

    evidence_id: str
    criterion_id: str
    a_static: float
    d_eff: float
    cap_static: float
    i: float
    f: float
    flaky_f: float
    tamper_penalty: float
    q: float
    l_cs: float
    l_st: float
    r_ct: float
    l: float  # noqa: E741
    term: float
    status: str
    d_mut: float | None = None  # no mutation data in the alpha
    lambda_kind: float = 1.0
    group_symbol: str | None = None
    rank_in_group: int | None = None
    discount: float | None = None
    contribution: float | None = None
    path: ChainRef | None = None
    algo_version: str = EVIDENCE_QUALITY_VERSION


#: Alias used in the design discussion.
QualityBreakdown = EvidenceQuality
