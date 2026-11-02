"""Default extractor set shared by the API and the worker (IN-02)."""

from __future__ import annotations

from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    ExtractionConfig,
    normalize_mode,
)
from radius_intent.infrastructure.manual import ManualCriterionExtractor
from radius_intent.interfaces import CriterionExtractor


def default_extractors(extraction_mode: str | None = None) -> tuple[CriterionExtractor, ...]:
    """Return the extractors every intent pipeline starts with, in priority order.

    Order is the tie-break index of ``select_criteria``. An optional LLM extractor
    (IN-04) is appended by the composition root when it is enabled, never here.

    ``extraction_mode`` is ``sections`` (default; unknown values fall back to it) or
    ``summary`` (opt-in, see ``docs/verdict-v2.md``).
    """
    config = ExtractionConfig(mode=normalize_mode(extraction_mode))
    return (ManualCriterionExtractor(), DeterministicCriterionExtractor(config))


__all__ = ["default_extractors"]
