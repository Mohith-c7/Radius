"""Seeded cluster bootstrap and agreement statistics (IN-10, pure Python).

Clusters are PRs: a *vector* is one PR's additive counts (sparse
``{key: number}``). A bootstrap replicate draws ``n`` PRs with replacement,
sums their vectors and evaluates the metric function on the totals, so ratios
(micro P/R/F1) and per-PR macro means are both resampled at the PR level, as
the preregistration requires (PREREGISTRATION 2 and 5.4: percentile 95%
intervals, cluster resampling, master seed 20261102).

Determinism: a replicate depends only on ``seed`` and on the sorted order of
the clusters, drawn with ``random.Random(seed)``; the same seed and data give
bit-identical intervals on any platform running CPython 3.12.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

SparseVec = Mapping[str, float]
MetricFn = Callable[[Mapping[str, float]], Mapping[str, float | None]]

DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Interval:
    """Point estimate with a percentile interval (``None`` when undefined)."""

    estimate: float | None
    low: float | None
    high: float | None
    n_valid: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "n_valid": self.n_valid,
        }


@dataclass(frozen=True)
class DiffInterval:
    """Paired difference (A - B) with a percentile interval."""

    estimate: float | None
    low: float | None
    high: float | None
    n_valid: int
    p_value: float | None

    @property
    def excludes_zero(self) -> bool:
        return (
            self.low is not None
            and self.high is not None
            and (self.low > 0 or self.high < 0)
        )

    def as_dict(self) -> dict[str, float | int | bool | None]:
        return {
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "n_valid": self.n_valid,
            "p_value": self.p_value,
            "excludes_zero": self.excludes_zero,
        }


def sum_vectors(vectors: Sequence[SparseVec]) -> dict[str, float]:
    """Add sparse vectors key-wise (iteration order is the sequence order)."""
    total: dict[str, float] = {}
    for vec in vectors:
        for key, value in vec.items():
            total[key] = total.get(key, 0) + value
    return total


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (``q`` in [0, 1]) of sorted values."""
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    if not 0 <= q <= 1:
        raise ValueError("q must be in [0, 1]")
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _interval(values: list[float], confidence: float) -> tuple[float, float] | None:
    if not values:
        return None
    values.sort()
    alpha = (1 - confidence) / 2
    return percentile(values, alpha), percentile(values, 1 - alpha)


def _check(resamples: int, confidence: float, n: int) -> None:
    if resamples < 1:
        raise ValueError("resamples must be >= 1")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")
    if n < 1:
        raise ValueError("bootstrap needs at least one cluster")


def bootstrap_metrics(
    vectors: Sequence[SparseVec],
    metric_fn: MetricFn,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, Interval]:
    """Cluster-bootstrap every metric returned by ``metric_fn``.

    ``vectors`` must be in a canonical order (the harness sorts by case id).
    """
    n = len(vectors)
    _check(resamples, confidence, n)
    point = metric_fn(sum_vectors(vectors))
    draws: dict[str, list[float]] = {name: [] for name in point}
    rng = random.Random(seed)
    for _ in range(resamples):
        total: dict[str, float] = {}
        for _i in range(n):
            for key, value in vectors[rng.randrange(n)].items():
                total[key] = total.get(key, 0) + value
        for name, value in metric_fn(total).items():
            if value is not None and not math.isnan(value):
                draws.setdefault(name, []).append(value)
    out: dict[str, Interval] = {}
    for name, estimate in point.items():
        values = draws.get(name, [])
        bounds = _interval(values, confidence)
        out[name] = Interval(
            estimate,
            bounds[0] if bounds else None,
            bounds[1] if bounds else None,
            len(values),
        )
    return out


def paired_bootstrap_diff(
    vectors_a: Sequence[SparseVec],
    vectors_b: Sequence[SparseVec],
    metric_fn: MetricFn,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, DiffInterval]:
    """Paired cluster bootstrap of ``metric(A) - metric(B)``.

    Both sequences must describe the same clusters in the same order. Each
    replicate uses the same drawn clusters for A and B. ``p_value`` is the
    two-sided bootstrap tail share ``2 * min(P(d <= 0), P(d >= 0))`` floored
    at ``1 / (resamples + 1)``; it is an approximation reported for Holm
    adjustment, not an exact test.
    """
    if len(vectors_a) != len(vectors_b):
        raise ValueError("paired bootstrap needs the same clusters on both sides")
    n = len(vectors_a)
    _check(resamples, confidence, n)
    pa = metric_fn(sum_vectors(vectors_a))
    pb = metric_fn(sum_vectors(vectors_b))
    names = sorted(set(pa) | set(pb))
    draws: dict[str, list[float]] = {name: [] for name in names}
    rng = random.Random(seed)
    for _ in range(resamples):
        ta: dict[str, float] = {}
        tb: dict[str, float] = {}
        for _i in range(n):
            k = rng.randrange(n)
            for key, value in vectors_a[k].items():
                ta[key] = ta.get(key, 0) + value
            for key, value in vectors_b[k].items():
                tb[key] = tb.get(key, 0) + value
        ma, mb = metric_fn(ta), metric_fn(tb)
        for name in names:
            x, y = ma.get(name), mb.get(name)
            if x is not None and y is not None and not (math.isnan(x) or math.isnan(y)):
                draws[name].append(x - y)
    out: dict[str, DiffInterval] = {}
    for name in names:
        x, y = pa.get(name), pb.get(name)
        estimate = x - y if x is not None and y is not None else None
        values = draws[name]
        bounds = _interval(list(values), confidence)
        p_value = None
        if values:
            le = sum(1 for v in values if v <= 0)
            ge = sum(1 for v in values if v >= 0)
            p_value = min(1.0, max(2 * min(le, ge) / len(values), 1 / (len(values) + 1)))
        out[name] = DiffInterval(
            estimate,
            bounds[0] if bounds else None,
            bounds[1] if bounds else None,
            len(values),
            p_value,
        )
    return out


def cohen_kappa(confusion: Mapping[tuple[str, str], float]) -> float | None:
    """Cohen's kappa from a ``{(gold, predicted): count}`` table.

    ``None`` when there are no items or chance agreement is 1 (a single
    category on both sides), where kappa is undefined.
    """
    total = sum(confusion.values())
    if total <= 0:
        return None
    rows: Counter[str] = Counter()
    cols: Counter[str] = Counter()
    agree = 0.0
    for (g, p), count in confusion.items():
        rows[g] += count
        cols[p] += count
        if g == p:
            agree += count
    po = agree / total
    pe = sum(rows[k] * cols[k] for k in rows) / (total * total)
    if pe >= 1 - 1e-12:
        return None
    return (po - pe) / (1 - pe)


def f1_score(precision: float | None, recall: float | None) -> float | None:
    """Harmonic mean; ``None`` if either is undefined, 0.0 if both are 0."""
    if precision is None or recall is None:
        return None
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0
