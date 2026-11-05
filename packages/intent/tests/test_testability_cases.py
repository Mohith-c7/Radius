"""Table-driven testability cases from the labeled fixtures.

The fixtures are a development sanity set written by the rater's author, not
a research result. ``KNOWN_MISSES`` lists the documented limitations; each
must stay a low-confidence miss so the rater does not claim certainty.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from radius_intent.domain import Testability
from radius_intent.infrastructure.testability import (
    Confidence,
    DeterministicTestabilityRater,
    evaluate,
    load_labeled,
)

FIXTURES = Path(__file__).parent / "fixtures" / "testability"
CASES = load_labeled(FIXTURES / "labeled.jsonl")
HOLDOUT = load_labeled(FIXTURES / "labeled_holdout.jsonl")

#: Documented limitations (see README): ids -> why.
KNOWN_MISSES = {
    "s19": "'Split ... into per-environment files' has no structural phrase",
    "l01": "Spanish: English word lists find no cue (low confidence by design)",
    "l06": "Chinese: only the code references are understood",
    "h04": "'Secure' matches the non-functional term list",
    "h28": "'approves' is not in the external-judgment list",
}

RATER = DeterministicTestabilityRater()


def test_fixture_size_and_coverage():
    assert len(CASES) >= 120
    labels = {c.label for c in CASES}
    assert labels == {
        Testability.BEHAVIORAL_TESTABLE,
        Testability.STRUCTURAL_CHECKABLE,
        Testability.NON_FUNCTIONAL_MEASURABLE,
        Testability.SUBJECTIVE_OR_VAGUE,
        Testability.UNTESTABLE_EXTERNAL,
    }
    assert sum(1 for c in CASES if c.lang != "en") >= 8
    assert len({c.case_id for c in CASES + HOLDOUT}) == len(CASES) + len(HOLDOUT)


@pytest.mark.parametrize("case", CASES + HOLDOUT, ids=lambda c: c.case_id)
def test_labeled_case(case):
    result = RATER.rate_text(case.text, tests=case.tests, source_kind=case.source_kind)
    if case.case_id in KNOWN_MISSES:
        assert result.rating is not case.label, "limitation fixed: remove from list"
        assert result.confidence is not Confidence.HIGH
    else:
        assert result.rating is case.label, result.to_dict()
    assert result.reasons or result.rating is Testability.SUBJECTIVE_OR_VAGUE
    assert result.rationale().endswith("]")


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.lang != "en"], ids=lambda c: c.case_id
)
def test_non_english_is_always_low_confidence(case):
    result = RATER.rate_text(case.text)
    if "non_english_fallback" in result.rule_ids:
        assert result.confidence is Confidence.LOW


def test_accuracy_floor_and_calibration():
    dev = evaluate(CASES)
    held = evaluate(HOLDOUT)
    assert dev.accuracy >= 0.95
    assert held.accuracy >= 0.9
    # High and medium confidence ratings are (almost) always right.
    by = {band: (ok, n) for band, ok, n in dev.by_confidence}
    assert by["high"][0] == by["high"][1] > 0
    assert by["medium"][0] / by["medium"][1] >= 0.95
    # Confidence bands are informative: low is the least accurate band.
    assert by["low"][0] / by["low"][1] < by["medium"][0] / by["medium"][1]
    text = dev.format()
    assert "accuracy" in text and "mistakes" in text
