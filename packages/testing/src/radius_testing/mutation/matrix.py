"""Kill matrix, per-test ``d_mut`` and per-criterion aggregation (EV-05).

Definitions (all counts over *decided, non-equivalent* mutants of the symbols
linked to the criterion):

* decided = status ``killed`` or ``survived``. ``timeout``, ``error`` and ``flaky``
  mutants are not attributable to a test and are excluded (and reported).
* non-equivalent = not flagged ``equivalent_suspect`` (when ``exclude_suspects``).
* ``d_mut(t) = killed_by(t) / N`` with ``N`` the number of such mutants. ``None`` when
  ``N < min_mutants`` (not enough sample: the caller falls back to the static cap).
* Credit: ``multi`` (default) gives every killing test a full kill; ``split`` gives
  ``1/k`` to each of ``k`` killing tests.
* The Wilson score interval bounds the point estimate; ``lcb`` is the conservative
  value a consumer should use. With ``credit="split"`` the interval is approximate
  (fractional successes).
* Criterion level: ``D(c) = |mutants killed by any linked test| / N`` (union, no
  double counting, unlike the noisy-OR over tests).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

KILLED = "killed"
SURVIVED = "survived"
DECIDED = frozenset({KILLED, SURVIVED})


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; ``(0, 1)`` when ``n == 0``."""

    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass(frozen=True, slots=True)
class MutantRecord:
    id: str
    symbol: str
    operator: str
    status: str  # killed | survived | timeout | error | flaky
    killed_by: frozenset[str] = frozenset()
    equivalent_suspect: bool = False
    location: str = ""


@dataclass(frozen=True, slots=True)
class KillMatrix:
    """Mutants x tests. ``tests`` are the baseline-passing tests that were run."""

    records: tuple[MutantRecord, ...]
    tests: tuple[str, ...]

    def selected(
        self, symbols: Iterable[str] | None = None, *, exclude_suspects: bool = True
    ) -> list[MutantRecord]:
        wanted = None if symbols is None else set(symbols)
        return [
            r
            for r in self.records
            if r.status in DECIDED
            and (wanted is None or r.symbol in wanted)
            and not (exclude_suspects and r.equivalent_suspect)
        ]

    def excluded(self, symbols: Iterable[str] | None = None) -> dict[str, list[str]]:
        """Mutant ids left out of the denominator, by reason (never silently dropped)."""

        wanted = None if symbols is None else set(symbols)
        out: dict[str, list[str]] = {}
        for r in self.records:
            if wanted is not None and r.symbol not in wanted:
                continue
            if r.equivalent_suspect:
                out.setdefault("equivalent_suspect", []).append(r.id)
            elif r.status not in DECIDED:
                out.setdefault(r.status, []).append(r.id)
        return out


@dataclass(frozen=True, slots=True)
class TestDetection:
    __test__ = False  # not a pytest class

    test: str
    killed: float
    n: int
    d_mut: float | None
    lcb: float | None
    ucb: float | None
    reason: str | None = None  # "insufficient_sample" when d_mut is None


@dataclass(frozen=True, slots=True)
class CriterionDetection:
    n_mutants: int
    killed_by_any: int
    union_d: float | None
    union_lcb: float | None
    per_test: tuple[TestDetection, ...]
    survivors: tuple[str, ...]
    excluded: Mapping[str, list[str]] = field(default_factory=dict)
    reason: str | None = None


def d_mut_per_test(
    matrix: KillMatrix,
    symbols: Iterable[str] | None = None,
    *,
    tests: Sequence[str] | None = None,
    min_mutants: int = 5,
    credit: str = "multi",
    exclude_suspects: bool = True,
    z: float = 1.96,
    reach: Mapping[str, Collection[str]] | None = None,
) -> tuple[TestDetection, ...]:
    """Per-test ``d_mut``.

    ``reach`` (optional) maps a test id to the mutant ids whose line the test
    executes. When given, the denominator for test ``t`` is only the mutants ``t``
    reaches ("conditional detection": would ``t`` have noticed, given it ran the
    mutated code?). A test absent from ``reach`` reaches nothing.
    """

    if credit not in {"multi", "split"}:
        raise ValueError("credit must be 'multi' or 'split'")
    full_pool = matrix.selected(symbols, exclude_suspects=exclude_suspects)
    wanted = tuple(tests) if tests is not None else matrix.tests
    out: list[TestDetection] = []
    for t in wanted:
        pool = full_pool if reach is None else [r for r in full_pool if r.id in reach.get(t, ())]
        n = len(pool)
        killed = 0.0
        for r in pool:
            if r.status == KILLED and t in r.killed_by:
                killed += 1.0 if credit == "multi" else 1.0 / len(r.killed_by)
        if n < min_mutants:
            out.append(TestDetection(t, killed, n, None, None, None, "insufficient_sample"))
            continue
        lo, hi = wilson_interval(killed, n, z)
        out.append(TestDetection(t, killed, n, killed / n, lo, hi))
    return tuple(out)


def aggregate_criterion(
    matrix: KillMatrix,
    symbols: Iterable[str],
    tests: Sequence[str],
    *,
    min_mutants: int = 5,
    credit: str = "multi",
    exclude_suspects: bool = True,
    z: float = 1.96,
) -> CriterionDetection:
    """Aggregate for one criterion: its linked ``symbols`` and linked ``tests``."""

    syms = list(symbols)
    pool = matrix.selected(syms, exclude_suspects=exclude_suspects)
    linked = set(tests)
    killed_any = [r for r in pool if r.status == KILLED and (r.killed_by & linked)]
    survivors = tuple(r.id for r in pool if r not in killed_any)
    per_test = d_mut_per_test(
        matrix, syms, tests=tests, min_mutants=min_mutants, credit=credit,
        exclude_suspects=exclude_suspects, z=z,
    )
    n = len(pool)
    excluded = matrix.excluded(syms)
    if n < min_mutants:
        return CriterionDetection(
            n, len(killed_any), None, None, per_test, survivors, excluded, "insufficient_sample"
        )
    lo, _ = wilson_interval(len(killed_any), n, z)
    return CriterionDetection(
        n, len(killed_any), len(killed_any) / n, lo, per_test, survivors, excluded
    )
