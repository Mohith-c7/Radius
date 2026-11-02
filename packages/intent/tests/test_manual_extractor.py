"""ManualCriterionExtractor (IN-08)."""

from __future__ import annotations

from datetime import UTC, datetime

from radius_intent.domain import ExtractionMethod, IntentSource, IntentSourceKind
from radius_intent.infrastructure import ManualCriterionExtractor
from radius_intent.infrastructure.manual import (
    HUMAN_EXTRACTOR_VERSION,
    MANUAL_SOURCE_PREFIX,
    manual_source_id,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def _source(source_id: str, text: str, kind=IntentSourceKind.COMMENT) -> IntentSource:
    return IntentSource.from_text(source_id, kind, text, NOW)


def test_manual_source_yields_one_human_criterion() -> None:
    text = "Audit logs are kept for 90 days"
    source = _source(manual_source_id(text), f"  {text}\n")

    (criterion,) = ManualCriterionExtractor().extract(source)

    assert criterion.text == text
    assert criterion.origin.extraction_method is ExtractionMethod.HUMAN
    assert criterion.origin.extractor_version == HUMAN_EXTRACTOR_VERSION
    assert criterion.span.slice(source.text) == text


def test_source_id_is_stable_under_case_and_whitespace() -> None:
    assert manual_source_id("Logs  kept") == manual_source_id(" logs kept ")
    assert manual_source_id("Logs kept").startswith(MANUAL_SOURCE_PREFIX)


def test_other_sources_are_ignored() -> None:
    extractor = ManualCriterionExtractor()

    assert extractor.extract(_source("manual:abc", "x", IntentSourceKind.PR_BODY)) == ()
    assert extractor.extract(_source("other", "Users must log in")) == ()
    assert extractor.extract(_source("manual:abc", "   \n")) == ()
