"""Ports can be satisfied structurally; package metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from radius_intent import __version__
from radius_intent.domain import (
    Criterion,
    ExtractionMethod,
    IntentSource,
    IntentSourceKind,
    Span,
    Testability,
    TestabilityAssessment,
)
from radius_intent.interfaces import (
    CriterionExtractor,
    IntentSourceFetcher,
    TestabilityRater,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)


class FakeFetcher:
    def fetch(self, analysis_id, kind, reference):
        if reference == "missing":
            return None
        return IntentSource.from_text(reference, kind, "- must work", NOW)


class FakeExtractor:
    def extract(self, source):
        return (
            Criterion.create(
                source,
                Span(source.source_id, 2, len(source.text)),
                extraction_method=ExtractionMethod.DETERMINISTIC,
                extractor_version="fake",
            ),
        )


class FakeRater:
    def rate(self, criterion):
        return TestabilityAssessment(Testability.TESTABLE, "observable")


def test_ports_wire_together():
    fetcher: IntentSourceFetcher = FakeFetcher()
    extractor: CriterionExtractor = FakeExtractor()
    rater: TestabilityRater = FakeRater()
    assert fetcher.fetch("a", IntentSourceKind.ISSUE, "missing") is None
    source = fetcher.fetch("a", IntentSourceKind.ISSUE, "i1")
    assert source is not None
    (criterion,) = extractor.extract(source)
    assert rater.rate(criterion).rating is Testability.TESTABLE


def test_package_version():
    assert __version__ == "0.1.0"
