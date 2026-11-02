"""Default extractor set shared by the API and the worker (IN-02)."""

from __future__ import annotations

from radius_intent.infrastructure.extraction import DeterministicCriterionExtractor
from radius_intent.infrastructure.manual import ManualCriterionExtractor
from radius_intent.interfaces import CriterionExtractor


def default_extractors() -> tuple[CriterionExtractor, ...]:
    """Return the extractors every intent pipeline starts with, in priority order.

    Order is the tie-break index of ``select_criteria``. An optional LLM extractor
    (IN-04) is appended by the composition root when it is enabled, never here.
    """
    return (ManualCriterionExtractor(), DeterministicCriterionExtractor())


__all__ = ["default_extractors"]
