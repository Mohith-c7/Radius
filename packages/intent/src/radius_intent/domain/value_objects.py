"""Intent value objects: Span, SourceRef, Provenance, TestabilityAssessment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from radius_intent.domain.enums import ExtractionMethod, IntentSourceKind, Testability
from radius_intent.domain.errors import (
    InvalidCriterionError,
    InvalidProvenanceError,
    InvalidSourceError,
    InvalidSpanError,
)

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def is_sha256_hex(value: str) -> bool:
    """Return whether ``value`` is a lowercase SHA-256 hex digest."""
    return _SHA256_HEX.fullmatch(value) is not None


@dataclass(frozen=True)
class Span:
    """Half-open character range ``[start, end)`` in a named source text."""

    source_id: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise InvalidSpanError("Span source_id must be non-empty.")
        if self.start < 0:
            raise InvalidSpanError("Span start must be >= 0.")
        if self.end <= self.start:
            raise InvalidSpanError("Span end must be greater than start.")

    def within(self, text: str) -> bool:
        """Return whether the span fits inside ``text``."""
        return self.end <= len(text)

    def slice(self, text: str) -> str:
        """Return the covered text, or raise if the span exceeds ``text``."""
        if not self.within(text):
            raise InvalidSpanError("Span lies outside the source text.")
        return text[self.start : self.end]


@dataclass(frozen=True)
class SourceRef:
    """Lightweight reference to an intent source at a given content hash."""

    kind: IntentSourceKind
    source_id: str
    raw_text_hash: str

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise InvalidSourceError("Source id must be non-empty.")
        if not is_sha256_hex(self.raw_text_hash):
            raise InvalidSourceError("raw_text_hash must be a SHA-256 hex digest.")

    @property
    def key(self) -> str:
        """Identity string ``"<kind>:<source_id>"``.

        The hash is excluded on purpose so criterion ids survive an edit of
        unrelated text in the same source.
        """
        return f"{self.kind.value}:{self.source_id}"


@dataclass(frozen=True)
class Provenance:
    """Where and how a criterion came to be.

    ``retrieved_at`` is supplied by the caller; the domain never reads a clock.
    """

    source: SourceRef
    retrieved_at: datetime
    extraction_method: ExtractionMethod
    extractor_version: str

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise InvalidProvenanceError("retrieved_at must be timezone-aware.")
        if not self.extractor_version.strip():
            raise InvalidProvenanceError("extractor_version must be non-empty.")


@dataclass(frozen=True)
class TestabilityAssessment:
    """Result of a :class:`TestabilityRater`: a rating and optional rationale."""

    __test__ = False  # not a pytest class

    rating: Testability
    rationale: str | None = None

    def __post_init__(self) -> None:
        if self.rationale is not None and not self.rationale.strip():
            raise InvalidCriterionError("Rationale, if given, must be non-blank.")


@dataclass(frozen=True)
class CriterionHints:
    """Optional author-supplied hints that travel with a criterion.

    ``paths`` are repo-relative glob hints for linking, ``tests`` are explicit
    evidence references (``path::name``), ``label`` is the author's own short
    id (for example ``C1`` in ``.radius/intent.yml``). All are advisory: they
    never change the criterion id.
    """

    paths: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "tests", tuple(self.tests))
        for entry in (*self.paths, *self.tests):
            if not entry.strip():
                raise InvalidCriterionError("Hint entries must be non-blank.")
        if self.label is not None and not self.label.strip():
            raise InvalidCriterionError("Hint label, if given, must be non-blank.")

    @property
    def is_empty(self) -> bool:
        """Return whether no hint is set."""
        return not (self.paths or self.tests or self.label)
