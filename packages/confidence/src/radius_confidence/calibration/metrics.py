"""Calibration metrics: reliability bins, ECE, Brier, log loss.

Pure functions over ``scores`` (predicted probability that the label is 1) and
binary ``labels``. Nothing here fits anything or reads a clock. All values are
*sample estimates*; with small N they are dominated by noise (a perfectly
calibrated model has positive expected ECE, see ``PREREGISTRATION.md`` 7.5), so
callers that report numbers should go through ``evaluate_calibration`` in
``guards``, which refuses below a declared N.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ._validate import CalibrationInputError, check_scores_labels

BinStrategy = Literal["width", "mass"]
LOG_LOSS_EPS = 1e-15


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    """One bin of a reliability diagram.

    ``lower``/``upper`` are the bin's edges for equal-width bins, and the
    smallest/largest score inside it for equal-mass bins. An empty bin has
    ``count == 0`` and ``None`` means.
    """

    index: int
    lower: float
    upper: float
    count: int
    mean_confidence: float | None
    observed_frequency: float | None

    @property
    def gap(self) -> float | None:
        if self.count == 0:
            return None
        return abs(self.observed_frequency - self.mean_confidence)  # type: ignore[operator]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "mean_confidence": self.mean_confidence,
            "observed_frequency": self.observed_frequency,
        }


def _make_bin(
    index: int, lo: float, hi: float, ps: list[float], ys: list[int]
) -> ReliabilityBin:
    n = len(ps)
    if n == 0:
        return ReliabilityBin(index, lo, hi, 0, None, None)
    return ReliabilityBin(index, lo, hi, n, math.fsum(ps) / n, sum(ys) / n)


def _mass_groups(ps: list[float], n_bins: int) -> list[list[int]]:
    """Index groups for equal-mass binning (sizes differ by at most one)."""

    order = sorted(range(len(ps)), key=lambda i: (ps[i], i))
    k = min(n_bins, len(ps))
    base, extra = divmod(len(ps), k)
    groups, pos = [], 0
    for b in range(k):
        size = base + (1 if b < extra else 0)
        groups.append(order[pos : pos + size])
        pos += size
    return groups


def reliability_bins(
    scores: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> list[ReliabilityBin]:
    """Group predictions into bins.

    ``"width"``: ``n_bins`` equal-width bins over [0, 1]; bin ``i`` is
    ``[i/n, (i+1)/n)`` and the last bin also contains 1.0. Empty bins are kept.

    ``"mass"``: sort by score (stable, ties keep input order) and cut into
    ``n_bins`` groups whose sizes differ by at most one (the first
    ``N mod n_bins`` groups get the extra item). Tied scores can therefore be
    split across two bins; that is deliberate (exactly equal mass) and
    deterministic. If ``N < n_bins`` only ``N`` single-item bins are returned.
    """

    if n_bins < 1:
        raise CalibrationInputError("n_bins must be >= 1")
    ps, ys = check_scores_labels(scores, labels)
    if strategy == "width":
        buckets: list[tuple[list[float], list[int]]] = [([], []) for _ in range(n_bins)]
        for p, y in zip(ps, ys, strict=True):
            idx = min(int(p * n_bins), n_bins - 1)
            buckets[idx][0].append(p)
            buckets[idx][1].append(y)
        return [
            _make_bin(i, i / n_bins, (i + 1) / n_bins, b[0], b[1])
            for i, b in enumerate(buckets)
        ]
    if strategy == "mass":
        out: list[ReliabilityBin] = []
        for b, idxs in enumerate(_mass_groups(ps, n_bins)):
            bp = [ps[i] for i in idxs]
            by = [ys[i] for i in idxs]
            out.append(_make_bin(b, min(bp), max(bp), bp, by))
        return out
    raise CalibrationInputError(f"unknown binning strategy {strategy!r}")


def expected_calibration_error(bins: Sequence[ReliabilityBin]) -> float:
    """ECE = sum_k (n_k / N) * |observed_k - mean_confidence_k|."""

    total = sum(b.count for b in bins)
    if total == 0:
        raise CalibrationInputError("no data")
    return math.fsum(b.count * b.gap for b in bins if b.count) / total  # type: ignore[operator]


def max_calibration_error(bins: Sequence[ReliabilityBin]) -> float:
    """MCE = max over non-empty bins of the absolute gap."""

    gaps = [b.gap for b in bins if b.count]
    if not gaps:
        raise CalibrationInputError("no data")
    return max(gaps)  # type: ignore[type-var]


def ece(
    scores: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> float:
    """Convenience: ECE of ``scores`` against ``labels``."""

    return expected_calibration_error(reliability_bins(scores, labels, n_bins, strategy))


def brier_score(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Mean squared error between probability and 0/1 outcome (lower is better)."""

    ps, ys = check_scores_labels(scores, labels)
    return math.fsum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / len(ps)


def log_loss(
    scores: Sequence[float], labels: Sequence[int], eps: float = LOG_LOSS_EPS
) -> float:
    """Mean negative log-likelihood (natural log); scores are clipped to [eps, 1-eps].

    The clipping makes isotonic outputs of exactly 0 or 1 finite; the value is
    then dominated by ``eps`` for any confident mistake, so read it together
    with the Brier score.
    """

    if not 0.0 < eps < 0.5:
        raise CalibrationInputError("eps must be in (0, 0.5)")
    ps, ys = check_scores_labels(scores, labels)
    total = 0.0
    for p, y in zip(ps, ys, strict=True):
        q = min(max(p, eps), 1.0 - eps)
        total += -math.log(q if y == 1 else 1.0 - q)
    return total / len(ps)


@dataclass(frozen=True, slots=True)
class BrierDecomposition:
    """Murphy-style decomposition over bins.

    ``brier = reliability - resolution + uncertainty + within_bin`` holds
    exactly (floating point aside). ``within_bin`` is the part the binned
    decomposition cannot attribute (variance of scores inside a bin and their
    covariance with the outcome); it is 0 when every bin holds one distinct
    score.
    """

    brier: float
    reliability: float
    resolution: float
    uncertainty: float
    within_bin: float

    def to_dict(self) -> dict:
        return {
            "brier": self.brier,
            "reliability": self.reliability,
            "resolution": self.resolution,
            "uncertainty": self.uncertainty,
            "within_bin": self.within_bin,
        }


def brier_decomposition(
    scores: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> BrierDecomposition:
    if n_bins < 1:
        raise CalibrationInputError("n_bins must be >= 1")
    ps, ys = check_scores_labels(scores, labels)
    n = len(ps)
    base = sum(ys) / n
    if strategy == "width":
        by_bin: dict[int, list[int]] = {}
        for i, p in enumerate(ps):
            by_bin.setdefault(min(int(p * n_bins), n_bins - 1), []).append(i)
        members = list(by_bin.values())
    elif strategy == "mass":
        members = _mass_groups(ps, n_bins)
    else:
        raise CalibrationInputError(f"unknown binning strategy {strategy!r}")
    rel = res = within = 0.0
    for idxs in members:
        m = len(idxs)
        pbar = math.fsum(ps[i] for i in idxs) / m
        obar = sum(ys[i] for i in idxs) / m
        rel += m * (pbar - obar) ** 2
        res += m * (obar - base) ** 2
        within += math.fsum(
            (ps[i] - pbar) ** 2 - 2 * (ps[i] - pbar) * (ys[i] - obar) for i in idxs
        )
    return BrierDecomposition(
        brier=brier_score(ps, ys),
        reliability=rel / n,
        resolution=res / n,
        uncertainty=base * (1 - base),
        within_bin=within / n,
    )


def reliability_curve(
    scores: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: BinStrategy = "width",
) -> list[dict]:
    """Plot-ready data for a reliability diagram (non-empty bins only).

    Each point: ``mean_confidence`` (x), ``observed_frequency`` (y), ``count``
    and the bin edges. A perfectly calibrated predictor lies on y = x.
    """

    return [
        b.to_dict() for b in reliability_bins(scores, labels, n_bins, strategy) if b.count
    ]
