"""Criterion entity: one atomic, testable statement of intent."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType

from radius_intent.domain.enums import (
    CriterionState,
    ExtractionMethod,
    Testability,
)
from radius_intent.domain.errors import (
    InvalidCriterionError,
    InvalidSpanError,
    InvalidStateTransitionError,
    InvalidWeightError,
)
from radius_intent.domain.identity import criterion_id, normalize_text
from radius_intent.domain.source import IntentSource
from radius_intent.domain.value_objects import CriterionHints, Provenance, Span

#: Allowed state transitions. Anything not listed is rejected.
ALLOWED_TRANSITIONS: MappingProxyType[CriterionState, frozenset[CriterionState]] = (
    MappingProxyType(
        {
            CriterionState.PROPOSED: frozenset(
                {
                    CriterionState.CONFIRMED,
                    CriterionState.REJECTED,
                    CriterionState.EDITED,
                }
            ),
            CriterionState.EDITED: frozenset(
                {
                    CriterionState.CONFIRMED,
                    CriterionState.REJECTED,
                    CriterionState.EDITED,
                    CriterionState.NEEDS_RECONFIRMATION,
                    CriterionState.ORPHANED,
                }
            ),
            CriterionState.CONFIRMED: frozenset(
                {
                    CriterionState.EDITED,
                    CriterionState.REJECTED,
                    CriterionState.NEEDS_RECONFIRMATION,
                    CriterionState.ORPHANED,
                }
            ),
            CriterionState.NEEDS_RECONFIRMATION: frozenset(
                {
                    CriterionState.CONFIRMED,
                    CriterionState.REJECTED,
                    CriterionState.EDITED,
                    CriterionState.ORPHANED,
                }
            ),
            CriterionState.ORPHANED: frozenset({CriterionState.REJECTED}),
            CriterionState.REJECTED: frozenset({CriterionState.PROPOSED}),
        }
    )
)


@dataclass(frozen=True)
class Criterion:
    """A criterion ``c``: statement, origin, weight, testability and state.

    The ``id`` is assigned at creation (see :func:`criterion_id`) and stays
    stable across edits, weight changes and state transitions.
    """

    id: str
    text: str
    normalized_text: str
    origin: Provenance
    span: Span
    weight: float = 1.0
    testability: Testability = Testability.UNRATED
    testability_rationale: str | None = None
    state: CriterionState = CriterionState.PROPOSED
    hints: CriterionHints = CriterionHints()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise InvalidCriterionError("Criterion id must be non-empty.")
        if not self.text.strip():
            raise InvalidCriterionError("Criterion text must be non-empty.")
        if not self.normalized_text or self.normalized_text != normalize_text(
            self.text
        ):
            raise InvalidCriterionError(
                "normalized_text must be non-empty and equal normalize_text(text)."
            )
        if not 0 < self.weight <= 1:  # also rejects NaN
            raise InvalidWeightError("Criterion weight must be in (0, 1].")
        if self.span.source_id != self.origin.source.source_id:
            raise InvalidSpanError("Span source_id must match the provenance source.")
        if self.testability_rationale is not None and not (
            self.testability_rationale.strip()
        ):
            raise InvalidCriterionError("Rationale, if given, must be non-blank.")

    @classmethod
    def create(
        cls,
        source: IntentSource,
        span: Span,
        *,
        extraction_method: ExtractionMethod,
        extractor_version: str,
        text: str | None = None,
        weight: float = 1.0,
        hints: CriterionHints = CriterionHints(),
    ) -> Criterion:
        """Create a PROPOSED criterion from ``source``.

        ``text`` defaults to the stripped span content. Enforces that the span
        names this source and lies within ``source.text``.
        """
        if span.source_id != source.source_id:
            raise InvalidSpanError("Span names a different source.")
        covered = span.slice(source.text)
        statement = covered.strip() if text is None else text
        normalized = normalize_text(statement)
        origin = Provenance(
            source=source.ref,
            retrieved_at=source.fetched_at,
            extraction_method=extraction_method,
            extractor_version=extractor_version,
        )
        return cls(
            id=criterion_id(normalized, source.ref.key),
            text=statement,
            normalized_text=normalized,
            origin=origin,
            span=span,
            weight=weight,
            hints=hints,
        )

    def transition_to(self, new_state: CriterionState) -> Criterion:
        """Return a copy in ``new_state`` or raise if the move is illegal."""
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            msg = f"Illegal transition {self.state.value} -> {new_state.value}."
            raise InvalidStateTransitionError(msg)
        return replace(self, state=new_state)

    def confirm(self) -> Criterion:
        """Human confirmed the criterion."""
        return self.transition_to(CriterionState.CONFIRMED)

    def reject(self) -> Criterion:
        """Human rejected the criterion."""
        return self.transition_to(CriterionState.REJECTED)

    def reopen(self) -> Criterion:
        """Return a rejected criterion to PROPOSED."""
        return self.transition_to(CriterionState.PROPOSED)

    def edit(self, new_text: str) -> Criterion:
        """Human edited the wording; keeps id, span and origin."""
        moved = self.transition_to(CriterionState.EDITED)
        return replace(moved, text=new_text, normalized_text=normalize_text(new_text))

    def with_weight(self, weight: float) -> Criterion:
        """Return a copy with a new weight in (0, 1]."""
        return replace(self, weight=weight)

    def with_hints(self, hints: CriterionHints) -> Criterion:
        """Return a copy with new linking hints."""
        return replace(self, hints=hints)

    def with_testability(
        self, rating: Testability, rationale: str | None = None
    ) -> Criterion:
        """Return a copy with a testability rating and optional rationale."""
        return replace(self, testability=rating, testability_rationale=rationale)
