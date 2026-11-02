"""Pipeline step: rate extracted criteria (integration point for IN-06).

IN-06's snapshot service calls :func:`rate_criteria` on the extractor output
before building the snapshot::

    criteria = extractor.extract(source)  # IN-03, UNRATED
    rated = rate_criteria(criteria)  # IN-05
    snapshot = IntentSnapshot(..., criteria=rated, ...)

The function is pure: it returns new criteria through
``Criterion.with_testability`` and never touches state, weight, text, id or
hints. Re-rating is idempotent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from radius_intent.domain import Criterion, Testability
from radius_intent.infrastructure.testability.rater import (
    DeterministicTestabilityRater,
)
from radius_intent.infrastructure.testability.result import TestabilityResult


@dataclass(frozen=True)
class RatingReport:
    """Rated criteria plus the full per-criterion results."""

    criteria: tuple[Criterion, ...]
    results: tuple[TestabilityResult, ...]

    def counts(self) -> dict[str, int]:
        """Number of criteria per rating (ratings with zero are omitted)."""
        out: dict[str, int] = {}
        for result in self.results:
            out[result.rating.value] = out.get(result.rating.value, 0) + 1
        return dict(sorted(out.items()))

    def needs_clarification(self) -> tuple[Criterion, ...]:
        """Criteria the author should reword (vague) or back with a proxy."""
        return tuple(
            c
            for c in self.criteria
            if c.testability
            in (Testability.SUBJECTIVE_OR_VAGUE, Testability.UNTESTABLE_EXTERNAL)
        )


def rate_criteria_report(
    criteria: Iterable[Criterion],
    rater: DeterministicTestabilityRater | None = None,
) -> RatingReport:
    """Rate every criterion; order is preserved."""
    active = rater if rater is not None else DeterministicTestabilityRater()
    rated: list[Criterion] = []
    results: list[TestabilityResult] = []
    for criterion in criteria:
        result = active.explain(criterion)
        rated.append(criterion.with_testability(result.rating, result.rationale()))
        results.append(result)
    return RatingReport(tuple(rated), tuple(results))


def rate_criteria(
    criteria: Iterable[Criterion],
    rater: DeterministicTestabilityRater | None = None,
) -> tuple[Criterion, ...]:
    """Return ``criteria`` with testability and rationale set (immutably)."""
    return rate_criteria_report(criteria, rater).criteria
