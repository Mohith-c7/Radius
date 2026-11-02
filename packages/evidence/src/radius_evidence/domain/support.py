"""Support S(c) result contract (design 3.9). The formula is VD-01's."""

from __future__ import annotations

from dataclasses import dataclass

from radius_evidence.domain.quality import EvidenceQuality
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import SUPPORT_VERSION


@dataclass(frozen=True, slots=True)
class SupportResult(Serializable):
    """Result of ``S(c)`` with every intermediate value kept for audit."""

    criterion_id: str
    S: float  # min(S_raw, s_cap)
    S_raw: float
    items: tuple[EvidenceQuality, ...]  # every item considered
    n_counted: int
    has_strong_item: bool
    algo_version: str = SUPPORT_VERSION
