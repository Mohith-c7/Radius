"""VerdictV2 contract (design 3.1 PR level, 3.9 and 3.10). Rules and tree: VD-03."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import TamperFindingInput
from radius_evidence.domain.model import Reason
from radius_evidence.domain.quality import EvidenceQuality
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import (
    ALGO_VERSION,
    JUSTIFICATION_SCHEMA,
    PROFILE_ALPHA_STATIC,
)


class Verdict(StrEnum):
    """DEC-008; equals the four DESIGN 6.5 states."""

    VERIFIED = "verified"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_REVIEW = "needs_review"


#: Rule ids in evaluation order (design 3.9). Every rule is recorded exactly once.
RULE_ORDER: tuple[str, ...] = (
    "R1a",
    "R1b",
    "R1c",
    "R2p",
    "R2a",
    "R2b",
    "R2c",
    "R2d",
    "R3a",
    "R3b",
    "R3c",
    "R4",
)


@dataclass(frozen=True, slots=True)
class RuleResult(Serializable):
    """One evaluated rule. ``refs`` keys: criterion_ids, evidence_ids, finding_ids."""

    id: str
    label: str
    fired: bool
    inputs: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JustificationNode(Serializable):
    """Root of the stored/served justification (schema verdict-v2-justification-1)."""

    verdict: Verdict
    decided_by: str
    rules: tuple[RuleResult, ...]
    thresholds: dict[str, Any] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    config_digest: str = ""
    profile: str = PROFILE_ALPHA_STATIC
    inputs_digest: str = ""
    schema: str = JUSTIFICATION_SCHEMA


@dataclass(frozen=True, slots=True)
class CriterionVerdict(Serializable):
    criterion_id: str
    text: str
    weight: float
    testability: str
    lifecycle: str
    state: SupportState
    S: float
    S_raw: float
    reasons: tuple[Reason, ...] = ()
    flags: tuple[Flag, ...] = ()
    items: tuple[EvidenceQuality, ...] = ()  # every item considered, usable or not
    best_link: dict[str, Any] = field(default_factory=dict)
    #: Contract 3: who supplied the criterion and each ``tests:``/``paths:`` hint.
    provenance: str = ""
    hints: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class VerdictV2(Serializable):
    analysis_id: str
    head_sha: str
    revision: int
    verdict: Verdict
    pending: bool
    reasons: tuple[Reason, ...]
    criteria: tuple[CriterionVerdict, ...]
    uim: float
    uim_numerator: float
    uim_denominator: float
    intent_coverage: float
    unlinked_symbols: tuple[str, ...]
    tamper: tuple[TamperFindingInput, ...]
    justification: dict[str, Any]
    config_digest: str
    inputs_digest: str
    algo_version: str = ALGO_VERSION
    profile: str = PROFILE_ALPHA_STATIC
    evidence_basis: str = "static_only"
