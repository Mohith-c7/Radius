"""Mutation budgets, deterministic seeded sampling and cache keys (EV-04/EV-09).

Sampling does not use :mod:`random`: each mutant gets a rank
``sha256(f"{seed}:{mutant.id}")`` so the selection is identical across Python
versions and processes. Selection is stratified round-robin over symbols, so one
large function cannot starve the others, then returned in canonical order.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from radius_testing.mutation.operators import Mutant


@dataclass(frozen=True, slots=True)
class MutationBudget:
    max_mutants: int = 50
    wall_clock_seconds: float = 900.0
    per_mutant_timeout_seconds: float = 60.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.max_mutants < 0:
            raise ValueError("max_mutants must be >= 0")
        if self.wall_clock_seconds <= 0 or self.per_mutant_timeout_seconds <= 0:
            raise ValueError("time budgets must be positive")


def _rank(seed: int, mutant_id: str) -> str:
    return hashlib.sha256(f"{seed}:{mutant_id}".encode()).hexdigest()


def sample_mutants(mutants: Sequence[Mutant], max_mutants: int, seed: int = 0) -> list[Mutant]:
    """Pick at most ``max_mutants``; all of them (canonical order) when under budget."""

    if max_mutants <= 0:
        return []
    if len(mutants) <= max_mutants:
        return list(mutants)
    groups: dict[str, list[Mutant]] = defaultdict(list)
    for m in mutants:
        groups[m.symbol].append(m)
    queues = [
        sorted(groups[sym], key=lambda m: (_rank(seed, m.id), m.id)) for sym in sorted(groups)
    ]
    picked: list[Mutant] = []
    depth = 0
    while len(picked) < max_mutants:
        progressed = False
        for queue in queues:
            if depth < len(queue) and len(picked) < max_mutants:
                picked.append(queue[depth])
                progressed = True
        if not progressed:
            break
        depth += 1
    order = {m.id: i for i, m in enumerate(mutants)}
    return sorted(picked, key=lambda m: order[m.id])


def set_hash_of_tests(test_ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(test_ids))).encode()).hexdigest()


def cache_key(
    mutant_hash: str, test_ids: Iterable[str], image_digest: str, context_hash: str = ""
) -> str:
    """EV-09 cache key: (mutant hash, test set hash, base image digest, context hash).

    ``context_hash`` must cover the *contents* of the selected tests and of the
    non-mutated sources they import; ids alone miss edited test bodies. The
    prototype leaves it empty unless the caller supplies it (see the design doc).
    """

    return hashlib.sha256(
        f"{mutant_hash}|{set_hash_of_tests(test_ids)}|{image_digest}|{context_hash}".encode()
    ).hexdigest()
