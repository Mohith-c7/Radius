"""Intent domain: pure types and invariants. Stdlib only, no I/O."""

from radius_intent.domain.criterion import ALLOWED_TRANSITIONS, Criterion
from radius_intent.domain.enums import (
    CriterionState,
    ExtractionMethod,
    IntentSourceKind,
    Testability,
)
from radius_intent.domain.errors import (
    DuplicateCriterionError,
    IntentDomainError,
    InvalidCriterionError,
    InvalidProvenanceError,
    InvalidSnapshotError,
    InvalidSourceError,
    InvalidSpanError,
    InvalidStateTransitionError,
    InvalidWeightError,
)
from radius_intent.domain.identity import (
    CRITERION_ID_ALGO,
    criterion_id,
    hash_text,
    normalize_text,
)
from radius_intent.domain.snapshot import (
    CriterionChange,
    IntentSnapshot,
    SnapshotDiff,
)
from radius_intent.domain.source import IntentSource
from radius_intent.domain.value_objects import (
    Provenance,
    SourceRef,
    Span,
    TestabilityAssessment,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "CRITERION_ID_ALGO",
    "Criterion",
    "CriterionChange",
    "CriterionState",
    "DuplicateCriterionError",
    "ExtractionMethod",
    "IntentDomainError",
    "IntentSnapshot",
    "IntentSource",
    "IntentSourceKind",
    "InvalidCriterionError",
    "InvalidProvenanceError",
    "InvalidSnapshotError",
    "InvalidSourceError",
    "InvalidSpanError",
    "InvalidStateTransitionError",
    "InvalidWeightError",
    "Provenance",
    "SnapshotDiff",
    "SourceRef",
    "Span",
    "Testability",
    "TestabilityAssessment",
    "criterion_id",
    "hash_text",
    "normalize_text",
]
