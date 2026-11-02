"""Per-criterion state and UIM result contracts (design 3.9). Logic is VD-02's."""

from __future__ import annotations

from dataclasses import dataclass

from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.model import Reason
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import PROFILE_ALPHA_STATIC


@dataclass(frozen=True, slots=True)
class CriterionStateResult(Serializable):
    criterion_id: str
    state: SupportState
    reasons: tuple[Reason, ...] = ()
    flags: tuple[Flag, ...] = ()


@dataclass(frozen=True, slots=True)
class UimResult(Serializable):
    """UIM = sum(w_c * [S(c) < tau]) / sum(w_c) over non-excluded criteria."""

    uim: float
    numerator: float
    denominator: float
    intent_coverage: float
    unproven_criterion_ids: tuple[str, ...] = ()
    excluded_criterion_ids: tuple[str, ...] = ()
    profile: str = PROFILE_ALPHA_STATIC
