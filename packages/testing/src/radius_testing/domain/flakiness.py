"""Flaky-test detection (F-11): rerun classification and the flakiness score.

Everything here is a pure function of its inputs. There is no wall clock, no
randomness and no I/O, so the same history always yields the same score.
See ``docs/FLAKY_TESTS.md`` for the definition and the rationale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

MAX_RERUNS = 10


class RerunVerdict(StrEnum):
    """Outcome of a test that failed once and was then rerun."""

    PASS = "pass"  # never failed (no rerun was needed)
    FLAKY = "flaky"  # failed, then passed on at least one rerun
    STABLE_FAIL = "stable_fail"  # failed on every attempt


class SampleOutcome(StrEnum):
    """Outcome of one recorded execution of a test."""

    PASSED = "passed"
    FAILED = "failed"
    FLAKY = "flaky"  # failed then passed within the same execution (rerun policy)


@dataclass(frozen=True, slots=True)
class RerunPolicy:
    """How many times a failing test is rerun in the sandbox.

    ``reruns=0`` (the default) disables the feature: nothing is rerun and no
    result can ever be classified flaky, so existing outputs are unchanged.
    """

    reruns: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.reruns <= MAX_RERUNS:
            raise ValueError(f"reruns must be between 0 and {MAX_RERUNS}")

    @property
    def enabled(self) -> bool:
        return self.reruns > 0


@dataclass(frozen=True, slots=True)
class FlakinessConfig:
    """Window and thresholds for the flakiness score."""

    window: int = 20
    """Number of most recent samples considered."""
    min_comparable: int = 3
    """Minimum comparable observations before a score is produced."""
    threshold: float = 0.2
    """Score at or above which a test is quarantined."""

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("window must be at least 2")
        if self.min_comparable < 1:
            raise ValueError("min_comparable must be at least 1")
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ExecutionSample:
    """One recorded execution of a test, oldest first in a history."""

    outcome: SampleOutcome
    code_key: str | None = None
    """Identity of the code under test (commit sha, or a covered-code hash).

    Two samples are only comparable when their keys are equal and not ``None``.
    """


@dataclass(frozen=True, slots=True)
class FlakinessAssessment:
    """Result of scoring one test's history."""

    score: float | None
    comparable: int
    flips: int
    samples_considered: int
    quarantined: bool

    @property
    def sufficient_history(self) -> bool:
        return self.score is not None


def classify_rerun(rerun_passes: Sequence[bool]) -> RerunVerdict:
    """Classify a test that already failed once, given its rerun results.

    ``rerun_passes`` holds one boolean per rerun that completed (True = passed).
    No completed rerun means no evidence of flakiness: ``STABLE_FAIL``.
    """

    return RerunVerdict.FLAKY if any(rerun_passes) else RerunVerdict.STABLE_FAIL


def flakiness_score(
    history: Sequence[ExecutionSample],
    config: FlakinessConfig | None = None,
) -> FlakinessAssessment:
    """Score a test's flakiness from its history (oldest first).

    Over the last ``config.window`` samples, count *comparable observations*:

    * consecutive pairs of pass/fail samples that ran the same code (equal,
      non-``None`` ``code_key``): a *flip* if the outcomes differ;
    * every ``FLAKY`` sample (failed then passed on rerun of identical code):
      one comparable observation that is always a flip.

    ``score = flips / comparable`` in ``[0, 1]``. Fewer than
    ``min_comparable`` observations yields ``score=None`` (never quarantined
    on thin evidence). A test that fails consistently or passes consistently
    scores 0; a failure fixed by a code change is not a flip because the
    code key differs.
    """

    cfg = config or FlakinessConfig()
    window = tuple(history[-cfg.window :])
    comparable = 0
    flips = 0
    previous: ExecutionSample | None = None
    for sample in window:
        if sample.outcome == SampleOutcome.FLAKY:
            comparable += 1
            flips += 1
            previous = None  # a flaky run has no single outcome to compare against
            continue
        if (
            previous is not None
            and previous.code_key is not None
            and previous.code_key == sample.code_key
        ):
            comparable += 1
            if previous.outcome != sample.outcome:
                flips += 1
        previous = sample
    if comparable < cfg.min_comparable:
        return FlakinessAssessment(None, comparable, flips, len(window), False)
    score = round(flips / comparable, 4)
    return FlakinessAssessment(score, comparable, flips, len(window), score >= cfg.threshold)
