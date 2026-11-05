"""Intent ports. Signatures only; adapters live in infrastructure."""

from __future__ import annotations

from typing import Protocol

from radius_intent.domain import (
    Criterion,
    IntentSource,
    IntentSourceKind,
    TestabilityAssessment,
)


class IntentSourceFetcher(Protocol):
    """Fetch one raw intent source for an analysis."""

    def fetch(
        self, analysis_id: str, kind: IntentSourceKind, reference: str
    ) -> IntentSource | None:
        """Return the source, or ``None`` when it is absent (not an error)."""


class CriterionExtractor(Protocol):
    """Extract proposed criteria from one source."""

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        """Return PROPOSED criteria whose spans lie within ``source.text``."""


class TestabilityRater(Protocol):
    """Rate how testable a criterion is."""

    __test__ = False  # not a pytest class

    def rate(self, criterion: Criterion) -> TestabilityAssessment:
        """Return a rating with an optional rationale."""
