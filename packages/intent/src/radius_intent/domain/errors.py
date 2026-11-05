"""Domain error hierarchy for the intent model."""

from __future__ import annotations


class IntentDomainError(ValueError):
    """Base class for every intent-domain invariant violation."""


class InvalidSpanError(IntentDomainError):
    """A span is malformed or lies outside its source text."""


class InvalidProvenanceError(IntentDomainError):
    """Provenance is malformed or inconsistent with its source."""


class InvalidSourceError(IntentDomainError):
    """An intent source is malformed."""


class InvalidCriterionError(IntentDomainError):
    """A criterion violates a field invariant (text, rationale, source link)."""


class InvalidWeightError(InvalidCriterionError):
    """A criterion weight is outside (0, 1]."""


class InvalidStateTransitionError(IntentDomainError):
    """A criterion state change is not in the allowed transition table."""


class InvalidSnapshotError(IntentDomainError):
    """A snapshot is malformed (version, parent, source refs)."""


class DuplicateCriterionError(InvalidSnapshotError):
    """Two criteria in one snapshot share a stable id."""
