"""Confidence intervals: seeded percentile bootstrap and Clopper-Pearson.

Stdlib only. The binomial machinery uses the regularized incomplete beta
function (Lentz continued fraction, as in the standard numerical recipes); the
tests cross-check it against direct summation of the binomial pmf.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

from ._validate import CalibrationInputError, check_scores_labels

# ---------------------------------------------------------------- binomial


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def regularized_beta(x: float, a: float, b: float) -> float:
    """I_x(a, b), the regularized incomplete beta function."""

    if a <= 0 or b <= 0:
        raise CalibrationInputError("beta parameters must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""

    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return regularized_beta(1.0 - p, n - k, k + 1)


def _check_kn(k: int, n: int) -> None:
    if n < 0 or not 0 <= k <= n:
        raise CalibrationInputError(f"need 0 <= k <= n, got k={k}, n={n}")


def clopper_pearson_upper(k: int, n: int, delta: float) -> float:
    """One-sided exact upper bound U: P(X <= k; U) = delta (coverage 1 - delta).

    ``n == 0`` returns 1.0 (no information).
    """

    _check_kn(k, n)
    if not 0.0 < delta < 1.0:
        raise CalibrationInputError("delta must be in (0, 1)")
    if n == 0 or k == n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if binomial_cdf(k, n, mid) > delta:
            lo = mid
        else:
            hi = mid
    return hi


def clopper_pearson_lower(k: int, n: int, delta: float) -> float:
    """One-sided exact lower bound L: P(X >= k; L) = delta."""

    _check_kn(k, n)
    if not 0.0 < delta < 1.0:
        raise CalibrationInputError("delta must be in (0, 1)")
    if n == 0 or k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 1.0 - binomial_cdf(k - 1, n, mid) < delta:
            lo = mid
        else:
            hi = mid
    return lo


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided exact (Clopper-Pearson) interval, alpha/2 in each tail."""

    if not 0.0 < confidence < 1.0:
        raise CalibrationInputError("confidence must be in (0, 1)")
    half = (1.0 - confidence) / 2.0
    return clopper_pearson_lower(k, n, half), clopper_pearson_upper(k, n, half)


# --------------------------------------------------------------- bootstrap


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 1]) of an already sorted list."""

    if not sorted_values:
        raise CalibrationInputError("no values")
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence: float
    n_resamples: int
    n_valid: int
    seed: int
    clustered: bool

    def to_dict(self) -> dict:
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "confidence": self.confidence,
            "n_resamples": self.n_resamples,
            "n_valid": self.n_valid,
            "seed": self.seed,
            "clustered": self.clustered,
        }


def bootstrap_ci(
    statistic: Callable[[list[float], list[int]], float | None],
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    seed: int,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    clusters: Sequence[Hashable] | None = None,
) -> BootstrapInterval:
    """Seeded percentile bootstrap of ``statistic(scores, labels)``.

    With ``clusters`` (one id per item) whole clusters are resampled with
    replacement, in sorted-id order for determinism: use this whenever items
    share a unit (several patches per task instance, PREREGISTRATION 2.1).
    ``statistic`` may return ``None`` for a degenerate resample (dropped;
    ``n_valid`` counts the rest). The seed is required: there is no hidden
    default. A percentile bootstrap is approximate and can undercover for small N
    or for statistics near a boundary (ECE is biased upward).
    """

    if n_resamples < 1:
        raise CalibrationInputError("n_resamples must be >= 1")
    if not 0.0 < confidence < 1.0:
        raise CalibrationInputError("confidence must be in (0, 1)")
    ps, ys = check_scores_labels(scores, labels)
    n = len(ps)
    rng = random.Random(seed)
    estimate = statistic(ps, ys)
    values: list[float] = []
    if clusters is None:
        for _ in range(n_resamples):
            idx = [rng.randrange(n) for _ in range(n)]
            v = statistic([ps[i] for i in idx], [ys[i] for i in idx])
            if v is not None and not math.isnan(v):
                values.append(v)
    else:
        if len(clusters) != n:
            raise CalibrationInputError("clusters must have one id per item")
        groups: dict[Hashable, list[int]] = {}
        for i, c in enumerate(clusters):
            groups.setdefault(c, []).append(i)
        keys = sorted(groups, key=repr)
        for _ in range(n_resamples):
            idx = []
            for _k in keys:
                idx.extend(groups[keys[rng.randrange(len(keys))]])
            v = statistic([ps[i] for i in idx], [ys[i] for i in idx])
            if v is not None and not math.isnan(v):
                values.append(v)
    values.sort()
    if not values:
        return BootstrapInterval(estimate, None, None, confidence, n_resamples, 0, seed, clusters is not None)
    tail = (1.0 - confidence) / 2.0
    return BootstrapInterval(
        estimate,
        percentile(values, tail),
        percentile(values, 1.0 - tail),
        confidence,
        n_resamples,
        len(values),
        seed,
        clusters is not None,
    )
