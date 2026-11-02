"""Accuracy helper for labeled testability cases (hook for IN-10).

The mini set under ``tests/fixtures/testability/labeled.jsonl`` is a
development sanity check, not a research result. One JSON object per line:
``{"id", "text", "label", "lang"?, "source"?, "tests"?}``.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from radius_intent.domain import IntentSourceKind, Testability
from radius_intent.infrastructure.testability.rater import (
    DeterministicTestabilityRater,
)

_RATED = tuple(t for t in dict.fromkeys(Testability) if t is not Testability.UNRATED)


class LabeledCaseError(ValueError):
    """A labeled-case line is malformed."""


@dataclass(frozen=True)
class LabeledCase:
    """One hand-labeled criterion."""

    case_id: str
    text: str
    label: Testability
    source_kind: IntentSourceKind | None = None
    tests: tuple[str, ...] = ()
    lang: str = "en"


@dataclass(frozen=True)
class LabelStats:
    """Precision, recall and support for one label."""

    label: str
    precision: float
    recall: float
    support: int


@dataclass(frozen=True)
class AccuracyReport:
    """Overall and per-label accuracy of a rater on labeled cases."""

    total: int
    correct: int
    per_label: tuple[LabelStats, ...]
    confusion: tuple[tuple[str, str, int], ...]
    by_confidence: tuple[tuple[str, int, int], ...]
    mistakes: tuple[tuple[str, str, str], ...]

    @property
    def accuracy(self) -> float:
        """Share of correctly rated cases (0.0 when there are none)."""
        return self.correct / self.total if self.total else 0.0

    def format(self) -> str:
        """Plain-text report."""
        lines = [
            f"accuracy {self.correct}/{self.total} = {self.accuracy:.3f}",
            "label                      precision recall support",
        ]
        for s in self.per_label:
            lines.append(
                f"{s.label:<26} {s.precision:9.2f} {s.recall:6.2f} {s.support:7d}"
            )
        lines.append("confidence  correct/total")
        for band, ok, n in self.by_confidence:
            lines.append(f"{band:<10}  {ok}/{n}")
        lines.append("mistakes (id: expected -> got)")
        lines.extend(f"{i}: {e} -> {g}" for i, e, g in self.mistakes)
        return "\n".join(lines)


def parse_labeled_line(line: str, number: int = 0) -> LabeledCase:
    """Parse one JSONL line or raise :class:`LabeledCaseError`."""
    try:
        obj = json.loads(line)
        label = Testability(obj["label"])
        if label is Testability.UNRATED:
            raise ValueError("label 'unrated' is not allowed")
        kind = IntentSourceKind(obj["source"]) if obj.get("source") else None
        return LabeledCase(
            case_id=str(obj["id"]),
            text=str(obj["text"]),
            label=label,
            source_kind=kind,
            tests=tuple(obj.get("tests", ())),
            lang=str(obj.get("lang", "en")),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LabeledCaseError(f"line {number}: {exc}") from exc


def load_labeled(path: str | Path) -> tuple[LabeledCase, ...]:
    """Read a JSONL file of labeled cases (blank lines are skipped)."""
    cases: list[LabeledCase] = []
    text = Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            cases.append(parse_labeled_line(line, number))
    return tuple(cases)


def evaluate(
    cases: Iterable[LabeledCase],
    rater: DeterministicTestabilityRater | None = None,
) -> AccuracyReport:
    """Rate every case and compare with its label."""
    active = rater if rater is not None else DeterministicTestabilityRater()
    pairs: list[tuple[LabeledCase, Testability, str]] = []
    for case in cases:
        result = active.rate_text(
            case.text, tests=case.tests, source_kind=case.source_kind
        )
        pairs.append((case, result.rating, result.confidence.value))
    confusion = Counter((c.label.value, got.value) for c, got, _ in pairs)
    per_label: list[LabelStats] = []
    for label in _RATED:
        tp = confusion[(label.value, label.value)]
        predicted = sum(n for (_, g), n in confusion.items() if g == label.value)
        actual = sum(n for (e, _), n in confusion.items() if e == label.value)
        per_label.append(
            LabelStats(
                label.value,
                tp / predicted if predicted else 0.0,
                tp / actual if actual else 0.0,
                actual,
            )
        )
    bands: dict[str, list[int]] = {"high": [0, 0], "medium": [0, 0], "low": [0, 0]}
    for case, got, band in pairs:
        bands[band][1] += 1
        bands[band][0] += int(case.label is got)
    return AccuracyReport(
        total=len(pairs),
        correct=sum(1 for c, g, _ in pairs if c.label is g),
        per_label=tuple(per_label),
        confusion=tuple(sorted((e, g, n) for (e, g), n in confusion.items())),
        by_confidence=tuple((b, v[0], v[1]) for b, v in bands.items()),
        mistakes=tuple(
            (c.case_id, c.label.value, g.value) for c, g, _ in pairs if c.label is not g
        ),
    )
