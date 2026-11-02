"""Deterministic (LLM-free) criterion extraction (IN-03)."""

from radius_intent.infrastructure.extraction.config import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    SOURCE_PRIORITY,
    ExtractionConfig,
)
from radius_intent.infrastructure.extraction.extractor import (
    DeterministicCriterionExtractor,
)
from radius_intent.infrastructure.extraction.metrics import (
    GoldCase,
    PrecisionRecall,
    score_by_source_kind,
    score_extraction,
)
from radius_intent.infrastructure.extraction.report import (
    CriterionTrace,
    Diagnostic,
    DiagnosticKind,
    DuplicateGroup,
    ExtractionReport,
    MergedOrigin,
    Severity,
)

__all__ = [
    "DETERMINISTIC_EXTRACTOR_VERSION",
    "SOURCE_PRIORITY",
    "CriterionTrace",
    "DeterministicCriterionExtractor",
    "Diagnostic",
    "DiagnosticKind",
    "DuplicateGroup",
    "ExtractionConfig",
    "ExtractionReport",
    "GoldCase",
    "MergedOrigin",
    "PrecisionRecall",
    "Severity",
    "score_by_source_kind",
    "score_extraction",
]
