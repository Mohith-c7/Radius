"""Extractor for human-authored criteria (IN-08).

A manual criterion is stored as a source of kind ``comment`` whose id starts
with :data:`MANUAL_SOURCE_PREFIX` and whose text is the criterion statement.
Keeping it a source means a rebuild re-derives it like any other criterion, and
the merge rules (``human`` outranks ``deterministic``) apply unchanged.
"""

from __future__ import annotations

from radius_intent.domain import (
    Criterion,
    ExtractionMethod,
    IntentSource,
    IntentSourceKind,
    Span,
)
from radius_intent.domain.identity import hash_text, normalize_text

#: Source-id prefix reserved for manual criteria.
MANUAL_SOURCE_PREFIX = "manual:"
HUMAN_EXTRACTOR_VERSION = "human-v1"


def manual_source_id(text: str) -> str:
    """Return the stable source id for a manual criterion statement."""
    return f"{MANUAL_SOURCE_PREFIX}{hash_text(normalize_text(text))[:16]}"


class ManualCriterionExtractor:
    """Emit one ``human`` criterion for each manual source; ignore all others."""

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        """Return the single criterion covering the whole manual source text."""
        if source.kind is not IntentSourceKind.COMMENT or not (
            source.source_id.startswith(MANUAL_SOURCE_PREFIX)
        ):
            return ()
        statement = source.text.strip()
        if not statement:
            return ()
        start = source.text.index(statement[0])
        span = Span(source.source_id, start, start + len(statement))
        return (
            Criterion.create(
                source,
                span,
                extraction_method=ExtractionMethod.HUMAN,
                extractor_version=HUMAN_EXTRACTOR_VERSION,
            ),
        )


__all__ = [
    "HUMAN_EXTRACTOR_VERSION",
    "MANUAL_SOURCE_PREFIX",
    "ManualCriterionExtractor",
    "manual_source_id",
]
