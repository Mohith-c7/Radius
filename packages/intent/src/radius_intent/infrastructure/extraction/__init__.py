"""Deterministic (LLM-free) criterion extraction (IN-03)."""

from radius_intent.infrastructure.extraction.config import (
    DEFAULT_EXTRACTION_MODE,
    DETERMINISTIC_EXTRACTOR_VERSION,
    EXTRACTION_MODES,
    SOURCE_PRIORITY,
    ExtractionConfig,
    normalize_mode,
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
from radius_intent.infrastructure.extraction.summary import (
    SUMMARY_EXTRACTOR_VERSION,
)

__all__ = [
    "DEFAULT_EXTRACTION_MODE",
    "EXTRACTION_MODES",
    "SUMMARY_EXTRACTOR_VERSION",
    "normalize_mode",
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
