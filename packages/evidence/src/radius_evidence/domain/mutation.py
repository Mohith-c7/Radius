"""Stage B use of the mutation kill matrix (contract 5; design MUTATION_EVIDENCE.md 8).

Pure functions of :class:`radius_evidence.domain.inputs.MutationInput`:

* :func:`measure_test` gives the measured detection power ``d_mut(t, c)`` of one test for
  one criterion over the **decided, non-equivalent** mutants of the changed symbols that
  are both linked to the criterion and were run with that test (decision D2). Timeouts,
  errors, flaky and skipped mutants and equivalent suspects are excluded and reported,
  never counted as survivors.
* :func:`measure_criterion` gives the criterion-level union ``D(c)`` (mutants killed by
  any counted test of the criterion, no double counting) and the survivors list
  ("Gaps found by mutation"). It is shown, it does not change ``S(c)`` in this slice
  (open decision D5 stays an ablation).

Nothing here decides a verdict. Survivors and unmeasured criteria only mean the static
cap applies; they never create ``verified`` or ``failed``.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from radius_evidence.domain.inputs import MutantInput, MutationInput
from radius_evidence.domain.quality import MutationMeasure
from radius_evidence.domain.serialization import Serializable

KILLED = "killed"
SURVIVED = "survived"
DECIDED = frozenset({KILLED, SURVIVED})

BASIS_STATIC = "static_only"
BASIS_MEASURED = "mutation_measured"
BASIS_MIXED = "mutation_partial"
#: Top-level payload basis when at least one criterion is (partly) mutation-measured.
PR_BASIS_MUTATION = "static_and_mutation"


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval; ``(0, 1)`` when ``n == 0``. Same formula as the producer."""

    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _pool(
    mutation: MutationInput, symbols: Collection[str], *, test_id: str | None = None
) -> list[MutantInput]:
    out = []
    for m in mutation.mutants:
        if m.symbol_id not in symbols or m.status not in DECIDED or m.equivalent_suspect:
            continue
        if test_id is not None and test_id not in mutation.symbol_tests.get(m.symbol_id, ()):
            continue
        out.append(m)
    return out


def measure_test(
    mutation: MutationInput | None, criterion_symbols: Collection[str], test_id: str
) -> MutationMeasure | None:
    """Measured detection of ``test_id`` for a criterion, or ``None`` when not applicable.

    ``None`` means "no mutation data for this pair" (flag off, unmeasured run, or the test
    was not run against any mutant of the criterion's symbols): the static cap applies
    without any reason code. A :class:`MutationMeasure` with ``measured=False`` means data
    exists but is too small.
    """

    if mutation is None or mutation.status != "measured":
        return None
    pool = _pool(mutation, criterion_symbols, test_id=test_id)
    if not pool:
        return None
    n = len(pool)
    killed = sum(1 for m in pool if m.status == KILLED and test_id in m.killed_by)
    if n < mutation.min_decided:
        return MutationMeasure(killed, n, None, None, False, mutation.min_decided)
    lcb, _ = wilson_interval(killed, n)
    return MutationMeasure(killed, n, killed / n, lcb, True, mutation.min_decided)


@dataclass(frozen=True, slots=True)
class Survivor(Serializable):
    mutant_id: str
    path: str
    line: int
    operator: str


@dataclass(frozen=True, slots=True)
class CriterionMutation(Serializable):
    """Mutation facts of one criterion (shown in the payload, contract 5)."""

    #: ``static_only`` | ``mutation_measured`` | ``mutation_partial``
    basis: str
    n_mutants: int = 0
    killed: int = 0
    d_union: float | None = None
    d_union_lcb: float | None = None
    tests_measured: int = 0
    tests_total: int = 0
    survivors: tuple[Survivor, ...] = ()
    excluded: dict[str, int] = field(default_factory=dict)
    #: Reachability-conditional detection is not computed in this slice (no per-test
    #: line coverage in the pipeline); reported as unavailable, never guessed.
    d_reach: float | None = None
    d_reach_reason: str = "no_reachability_data"
    reason: str = ""


def measure_criterion(
    mutation: MutationInput | None,
    criterion_symbols: Collection[str],
    counted_tests: Iterable[str],
    measured_tests: Collection[str],
) -> CriterionMutation:
    """Union detection ``D(c)``, survivors and the evidence basis of one criterion.

    ``counted_tests`` are the tests whose quality rows count for the criterion;
    ``measured_tests`` is the subset whose ``d_eff`` came from mutation.
    """

    tests = sorted(set(counted_tests))
    n_measured = sum(1 for t in tests if t in measured_tests)
    if tests and n_measured == len(tests):
        basis = BASIS_MEASURED
    elif n_measured:
        basis = BASIS_MIXED
    else:
        basis = BASIS_STATIC
    if mutation is None or mutation.status != "measured":
        reason = mutation.reason if mutation is not None else ""
        return CriterionMutation(BASIS_STATIC, tests_total=len(tests), reason=reason)
    run_symbols = {
        s
        for s in criterion_symbols
        if any(t in mutation.symbol_tests.get(s, ()) for t in tests)
    }
    pool = _pool(mutation, run_symbols)
    excluded: dict[str, int] = {}
    for m in mutation.mutants:
        if m.symbol_id not in run_symbols:
            continue
        if m.equivalent_suspect:
            excluded["equivalent_suspect"] = excluded.get("equivalent_suspect", 0) + 1
        elif m.status not in DECIDED:
            excluded[m.status] = excluded.get(m.status, 0) + 1
    linked = set(tests)
    killed = [m for m in pool if m.status == KILLED and linked & set(m.killed_by)]
    killed_ids = {m.mutant_id for m in killed}
    survivors = tuple(
        Survivor(m.mutant_id, m.path, m.line, m.operator)
        for m in sorted(pool, key=lambda x: (x.path, x.line, x.operator, x.mutant_id))
        if m.mutant_id not in killed_ids
    )
    n = len(pool)
    if n < mutation.min_decided:
        return CriterionMutation(
            basis,
            n_mutants=n,
            killed=len(killed),
            tests_measured=n_measured,
            tests_total=len(tests),
            survivors=survivors,
            excluded=excluded,
            reason="insufficient_sample",
        )
    lcb, _ = wilson_interval(len(killed), n)
    return CriterionMutation(
        basis,
        n_mutants=n,
        killed=len(killed),
        d_union=len(killed) / n,
        d_union_lcb=lcb,
        tests_measured=n_measured,
        tests_total=len(tests),
        survivors=survivors,
        excluded=excluded,
    )
