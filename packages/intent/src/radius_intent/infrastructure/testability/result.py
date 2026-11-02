"""Result types of the testability rater (all immutable, JSON-friendly)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from radius_intent.domain import Testability, TestabilityAssessment

#: Bump when any rule, weight, threshold or word-list default changes (plan 1.6).
TESTABILITY_RULES_VERSION = "testability-rules-v1"


class Confidence(StrEnum):
    """Confidence band of a rating (rule margins, not a probability)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Group(StrEnum):
    """Score group a rule feeds."""

    BEHAVIORAL = "behavioral"
    STRUCTURAL = "structural"
    NON_FUNCTIONAL = "non_functional"
    VAGUE = "vague"
    EXTERNAL = "external"
    META = "meta"


@dataclass(frozen=True)
class MatchSpan:
    """A matched character range ``[start, end)`` of the criterion text."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Reason:
    """One fired rule: id, score group, weight and the spans that matched."""

    rule_id: str
    group: Group
    weight: int
    spans: tuple[MatchSpan, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "rule_id": self.rule_id,
            "group": self.group.value,
            "weight": self.weight,
            "spans": [[s.start, s.end, s.text] for s in self.spans],
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TestabilityResult:
    """Full output of the rater for one criterion text."""

    __test__ = False  # not a pytest class

    rating: Testability
    confidence: Confidence
    reasons: tuple[Reason, ...]
    summary: str
    rewrite_hints: tuple[str, ...]
    scores: tuple[tuple[str, int], ...]
    rules_version: str = TESTABILITY_RULES_VERSION

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Ids of the fired rules in reason order."""
        return tuple(r.rule_id for r in self.reasons)

    def rationale(self) -> str:
        """One line for ``Criterion.testability_rationale``.

        Human sentence (plus the first rewrite hint for vague or external
        ratings) followed by a machine-readable tag.
        """
        text = self.summary
        if self.rewrite_hints:
            text = f"{text} Try: {self.rewrite_hints[0]}"
        ids = ",".join(self.rule_ids) or "none"
        return (
            f"{text} [{self.rules_version}; confidence={self.confidence.value}; "
            f"rules={ids}]"
        )

    def to_assessment(self) -> TestabilityAssessment:
        """Convert to the domain port result."""
        return TestabilityAssessment(self.rating, self.rationale())

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable form."""
        return {
            "rating": self.rating.value,
            "confidence": self.confidence.value,
            "summary": self.summary,
            "rewrite_hints": list(self.rewrite_hints),
            "reasons": [r.to_dict() for r in self.reasons],
            "scores": dict(self.scores),
            "rules_version": self.rules_version,
        }
