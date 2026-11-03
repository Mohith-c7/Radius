"""Calibrators: isotonic regression (PAV), Platt scaling, and the identity prior.

Stdlib only. These classes are *fitting* code: they do not decide whether N is
large enough to trust the result; ``guards.fit_calibrator`` does that and falls
back to :class:`UncalibratedPrior`.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from ._validate import CalibrationInputError, check_scores_labels
from .protocol import CalibratedScore, CalibrationState

PLATT_FEATURE_EPS = 1e-6


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass(frozen=True, slots=True)
class UncalibratedPrior:
    """The identity map, labelled for what it is.

    ``calibrate(x).value == x`` and ``state`` is ``UNCALIBRATED_PRIOR``. This is
    what a caller gets when there is not enough labelled data (and the only
    behaviour the product has today).
    """

    reason: str = "no calibrator fitted"
    n_fit: int = 0
    kind: str = "uncalibrated_prior"
    state: CalibrationState = CalibrationState.UNCALIBRATED_PRIOR

    def calibrate(self, raw: float) -> CalibratedScore:
        r = float(raw)
        if math.isnan(r) or not 0.0 <= r <= 1.0:
            raise CalibrationInputError(f"raw score must be in [0, 1], got {raw!r}")
        return CalibratedScore(r, self.state, self.kind, self.n_fit, r)

    def calibrate_many(self, raw: Sequence[float]) -> list[CalibratedScore]:
        return [self.calibrate(r) for r in raw]


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    """Monotone non-decreasing step/linear map fitted by pool-adjacent-violators.

    Scores with exactly equal value are pooled first, so the fit does not
    depend on input order. Each pooled block contributes two anchors (its
    lowest and highest score, both at the block mean); between blocks the map
    interpolates linearly, outside the fitted range it is clipped to the end
    values. Outputs are label means, hence in [0, 1]. Isotonic output can be
    exactly 0 or 1, which is overconfident for small N; this is why the
    preregistration draft prefers it only from 1,000 calibration items.
    """

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    n_fit: int
    kind: str = "isotonic"
    state: CalibrationState = CalibrationState.FITTED

    @classmethod
    def fit(cls, scores: Sequence[float], labels: Sequence[int]) -> IsotonicCalibrator:
        ps, ys = check_scores_labels(scores, labels)
        pooled: dict[float, list[int]] = {}
        for p, y in zip(ps, ys, strict=True):
            cell = pooled.setdefault(p, [0, 0])
            cell[0] += 1
            cell[1] += y
        # block: [x_lo, x_hi, weight, sum_y]
        blocks: list[list[float]] = []
        for x in sorted(pooled):
            w, s = pooled[x]
            blocks.append([x, x, float(w), float(s)])
            while len(blocks) > 1 and (
                blocks[-2][3] / blocks[-2][2] > blocks[-1][3] / blocks[-1][2]
            ):
                hi = blocks.pop()
                lo = blocks[-1]
                lo[1] = hi[1]
                lo[2] += hi[2]
                lo[3] += hi[3]
        ax: list[float] = []
        ay: list[float] = []
        for lo, hi, w, s in blocks:
            v = s / w
            ax.append(lo)
            ay.append(v)
            if hi != lo:
                ax.append(hi)
                ay.append(v)
        return cls(tuple(ax), tuple(ay), len(ps))

    def _value(self, x: float) -> float:
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        i = bisect_right(self.xs, x)  # xs[i-1] <= x < xs[i]
        x0, x1 = self.xs[i - 1], self.xs[i]
        y0, y1 = self.ys[i - 1], self.ys[i]
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def calibrate(self, raw: float) -> CalibratedScore:
        r = float(raw)
        if math.isnan(r) or not 0.0 <= r <= 1.0:
            raise CalibrationInputError(f"raw score must be in [0, 1], got {raw!r}")
        return CalibratedScore(
            _clip01(self._value(r)), self.state, self.kind, self.n_fit, r
        )

    def calibrate_many(self, raw: Sequence[float]) -> list[CalibratedScore]:
        return [self.calibrate(r) for r in raw]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "n_fit": self.n_fit, "xs": list(self.xs), "ys": list(self.ys)}


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    q = min(max(p, PLATT_FEATURE_EPS), 1.0 - PLATT_FEATURE_EPS)
    return math.log(q / (1.0 - q))


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    """Logistic map ``sigmoid(a * f(s) + b)`` fitted by Newton's method.

    ``f`` is ``logit(clip(s))`` (``feature="logit"``, default; right for scores
    that are already probabilities) or the raw score (``feature="raw"``). The
    targets use Platt's smoothing, ``(N+ + 1)/(N+ + 2)`` for positives and
    ``1/(N- + 2)`` for negatives, which keeps the fit finite on separable data.
    Needs at least one example of each class.
    """

    a: float
    b: float
    n_fit: int
    feature: str = "logit"
    kind: str = "platt"
    state: CalibrationState = CalibrationState.FITTED

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        labels: Sequence[int],
        *,
        feature: str = "logit",
        max_iter: int = 200,
        tol: float = 1e-10,
    ) -> PlattCalibrator:
        if feature not in ("logit", "raw"):
            raise CalibrationInputError("feature must be 'logit' or 'raw'")
        ps, ys = check_scores_labels(scores, labels)
        n_pos = sum(ys)
        n_neg = len(ys) - n_pos
        if n_pos == 0 or n_neg == 0:
            raise CalibrationInputError("Platt scaling needs both classes present")
        feats = [_logit(p) if feature == "logit" else p for p in ps]
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        targets = [t_pos if y == 1 else t_neg for y in ys]

        def nll(a: float, b: float) -> float:
            total = 0.0
            for f, t in zip(feats, targets, strict=True):
                z = a * f + b
                # log(1 + exp(z)) - t z, stable
                total += (z if z > 0 else 0.0) + math.log1p(math.exp(-abs(z))) - t * z
            return total

        a, b = 0.0, math.log((n_neg + 1.0) / (n_pos + 1.0))
        cur = nll(a, b)
        for _ in range(max_iter):
            ga = gb = haa = hab = hbb = 0.0
            for f, t in zip(feats, targets, strict=True):
                p = _sigmoid(a * f + b)
                d = p - t
                w = p * (1.0 - p)
                ga += d * f
                gb += d
                haa += w * f * f
                hab += w * f
                hbb += w
            haa += 1e-12
            hbb += 1e-12
            det = haa * hbb - hab * hab
            if det <= 0.0:
                break
            da = (hbb * ga - hab * gb) / det
            db = (-hab * ga + haa * gb) / det
            step = 1.0
            while step > 1e-12:
                na, nb = a - step * da, b - step * db
                new = nll(na, nb)
                if new <= cur + 1e-14:
                    break
                step *= 0.5
            else:
                break
            a, b, cur = na, nb, new
            if max(abs(step * da), abs(step * db)) < tol:
                break
        return cls(a, b, len(ps), feature)

    def calibrate(self, raw: float) -> CalibratedScore:
        r = float(raw)
        if math.isnan(r) or not 0.0 <= r <= 1.0:
            raise CalibrationInputError(f"raw score must be in [0, 1], got {raw!r}")
        f = _logit(r) if self.feature == "logit" else r
        return CalibratedScore(
            _sigmoid(self.a * f + self.b), self.state, self.kind, self.n_fit, r
        )

    def calibrate_many(self, raw: Sequence[float]) -> list[CalibratedScore]:
        return [self.calibrate(r) for r in raw]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "n_fit": self.n_fit,
            "a": self.a,
            "b": self.b,
            "feature": self.feature,
        }
