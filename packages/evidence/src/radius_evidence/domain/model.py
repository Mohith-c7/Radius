"""Evidence item and assertion-feature contracts (design 3.2 and 3.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from radius_evidence.domain.enums import (
    AssertKind,
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import ASSERTIONS_VERSION

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class Reason(Serializable):
    """Why something happened. ``rule_id`` (contract 2) names the deciding verdict rule
    (``R1c`` ...); ``ref`` stays the free reference (test id, path, finding id)."""

    code: str
    detail: str
    ref: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class AssertionFact(Serializable):
    kind: AssertKind
    line: int
    target_symbol_ids: tuple[str, ...] = ()  # LK-01 symbol ids, best effort
    compares_computed_value: bool = False
    note: str | None = None  # free text; flags below replaced the former note tokens
    # Contract 2: explicit strength-feature flags (all optional, default False).
    mock_only: bool = False
    circular: bool = False
    dead: bool = False
    swallowed: bool = False
    in_loop: bool = False
    property_based: bool = False


@dataclass(frozen=True, slots=True)
class AssertionFeatures(Serializable):
    """LK-04 output, one per test function (EV-06 input)."""

    test_id: str  # path::Class::function (normalize_test_id form)
    path: str
    line_start: int
    line_end: int
    assertions: tuple[AssertionFact, ...]
    n_assertions: int
    expects_exception: bool
    is_parametrized: bool
    n_param_cases: int | None
    has_skip_marker: bool
    name_terms: tuple[str, ...]  # used by VS-04
    literal_terms: tuple[str, ...]  # used by VS-04
    called_symbol_refs: tuple[str, ...] = ()
    algo_version: str = ASSERTIONS_VERSION


@dataclass(frozen=True, slots=True)
class FreshnessInfo(Serializable):
    """Binding of an item to a head SHA.

    ``reason``: ``current_head`` | ``stale_sha`` | ``unbound`` | ``stale_sha_unchanged_covered``
    (the optional decay hook: stale SHA but no covered file changed), see ``FRESHNESS_REASONS``.
    """

    bound_sha: str
    current_sha: str
    f: float
    reason: str


#: Allowed ``FreshnessInfo.reason`` values (contract 2 added the fourth).
FRESHNESS_REASONS: tuple[str, ...] = (
    "current_head",
    "stale_sha",
    "unbound",
    "stale_sha_unchanged_covered",
)

#: Alias used in the design discussion ("freshness binding").
FreshnessBinding = FreshnessInfo


@dataclass(frozen=True, slots=True)
class IndependenceInfo(Serializable):
    authored_by: AuthoredBy
    basis: IndependenceBasis
    factor: float
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class FlakyInfo(Serializable):
    flagged: bool
    source: str | None = None  # "rerun" | "history"
    score: float | None = None


@dataclass(frozen=True, slots=True)
class EvidenceItem(Serializable):
    evidence_id: str  # "ev_" + sha256(analysis_id|kind|subject|head_sha|algo)[:20]
    kind: EvidenceKind
    source: EvidenceSource
    analysis_id: str
    repository_id: str
    head_sha: str  # 40 lowercase hex; enforced (SHA-binding guarantee)
    subject_id: str  # test_id (TEST_OUTCOME) or finding_id (TAMPER_FINDING)
    path: str | None
    symbol_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]  # informational; EvidenceQuality is authoritative
    outcome: Outcome | None  # tests only
    duration_ms: int | None
    features: AssertionFeatures | None  # tests only
    severity: str | None  # findings only: info|low|medium|high|critical
    rule_id: str | None  # findings only
    independence: IndependenceInfo
    flaky: FlakyInfo
    freshness: FreshnessInfo
    reasons: tuple[Reason, ...]
    collected_at: str  # ISO-8601 UTC; excluded from inputs_digest
    algo_versions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _SHA40.match(self.head_sha):
            msg = "EvidenceItem.head_sha must be 40 lowercase hex characters"
            raise ValueError(msg)
