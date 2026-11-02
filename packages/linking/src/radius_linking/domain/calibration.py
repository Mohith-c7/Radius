"""Score calibration machinery (LK-06), pure Python, deterministic.

Calibration maps an uncalibrated link score to an estimate of
P(link is correct | score). It needs gold labels (IN-09 / LK-07), which do not
exist yet, so **nothing here is applied by default**: the chain combiner emits
``link_confidence_uncalibrated`` and only uses a calibrator when a fitted
:class:`CalibrationArtifact` is supplied.

Calibrators (all monotone non-decreasing in the score):

* :class:`BinningCalibrator` -- equal-width bins, empirical positive rate per bin
  (empty bins take the nearest non-empty bin to the left, else to the right).
* :class:`PlattCalibrator` -- ``p = 1 / (1 + exp(A * s + B))`` (scikit-learn's
  sigmoid convention) fitted by damped Newton on the Platt-smoothed targets
  ``t+ = (N+ + 1) / (N+ + 2)``, ``t- = 1 / (N- + 2)``; same objective as
  ``CalibratedClassifierCV(method="sigmoid")``.
* :class:`IsotonicCalibrator` -- weighted pool-adjacent-violators on the unique
  scores, applied by linear interpolation between block end points and clipped
  outside the fitted range (scikit-learn ``IsotonicRegression(out_of_bounds="clip")``).

Metrics: reliability bins, ECE, MCE, Brier. Artifacts are JSON with a version,
fit metadata and a SHA-256 over the canonical parameters.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

CALIBRATION_ARTIFACT_VERSION = "link-calibration-v1"
METHOD_BINNING = "binning"
METHOD_PLATT = "platt"
METHOD_ISOTONIC = "isotonic"
TARGET_CRITERION = "criterion"
TARGET_CHAIN = "chain"
_TARGETS = (TARGET_CRITERION, TARGET_CHAIN)


class CalibrationError(ValueError):
    """Invalid data for fitting, or an artifact that cannot be trusted."""


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 or math.isnan(x) else (1.0 if x > 1.0 else x)


def _check_xy(scores: Sequence[float], labels: Sequence[float]) -> None:
    if len(scores) != len(labels):
        raise CalibrationError("scores and labels must have the same length")
    if not scores:
        raise CalibrationError("cannot fit on empty data")
    for s in scores:
        if not 0.0 <= s <= 1.0:  # also rejects NaN
            raise CalibrationError("scores must be in [0, 1]")
    for y in labels:
        if y not in (0, 1):
            raise CalibrationError("labels must be 0 or 1")


class Calibrator(Protocol):
    """``fit`` returns ``self``; ``transform`` maps a score to a probability."""

    method: str

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> Calibrator: ...

    def transform(self, score: float) -> float: ...

    def params(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------- binning
class BinningCalibrator:
    method = METHOD_BINNING

    def __init__(self, n_bins: int = 10) -> None:
        if n_bins < 1:
            raise CalibrationError("n_bins must be >= 1")
        self.n_bins = n_bins
        self.values: list[float] | None = None

    def _bin(self, s: float) -> int:
        return min(self.n_bins - 1, int(_clip01(s) * self.n_bins))

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> BinningCalibrator:
        _check_xy(scores, labels)
        pos = [0] * self.n_bins
        cnt = [0] * self.n_bins
        for s, y in zip(scores, labels, strict=True):
            b = self._bin(s)
            cnt[b] += 1
            pos[b] += int(y)
        vals: list[float | None] = [
            (pos[i] / cnt[i] if cnt[i] else None) for i in range(self.n_bins)
        ]
        filled: list[float] = []
        last: float | None = None
        for v in vals:  # carry the previous bin forward
            last = v if v is not None else last
            filled.append(last if last is not None else math.nan)
        nxt: float | None = None
        for i in range(self.n_bins - 1, -1, -1):  # leading empties: next bin
            if vals[i] is not None:
                nxt = vals[i]
            if math.isnan(filled[i]):
                filled[i] = nxt if nxt is not None else 0.0
        self.values = filled
        return self

    def transform(self, score: float) -> float:
        if self.values is None:
            raise CalibrationError("calibrator is not fitted")
        return self.values[self._bin(score)]

    def params(self) -> dict[str, Any]:
        if self.values is None:
            raise CalibrationError("calibrator is not fitted")
        return {"n_bins": self.n_bins, "values": [round(v, 12) for v in self.values]}

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> BinningCalibrator:
        obj = cls(int(params["n_bins"]))
        values = [float(v) for v in params["values"]]
        if len(values) != obj.n_bins or any(not 0.0 <= v <= 1.0 for v in values):
            raise CalibrationError("invalid binning parameters")
        obj.values = values
        return obj


# ----------------------------------------------------------------------- Platt
def _sigmoid_neg(z: float) -> float:
    """``1 / (1 + exp(z))`` without overflow."""

    if z >= 0:
        e = math.exp(-z)
        return e / (1.0 + e)
    return 1.0 / (1.0 + math.exp(z))


class PlattCalibrator:
    method = METHOD_PLATT

    def __init__(self, max_iter: int = 100, tol: float = 1e-10) -> None:
        self.max_iter = max_iter
        self.tol = tol
        self.a: float | None = None
        self.b: float | None = None
        self.iterations = 0

    @staticmethod
    def _objective(f: Sequence[float], t: Sequence[float], a: float, b: float) -> float:
        total = 0.0
        for fi, ti in zip(f, t, strict=True):
            z = a * fi + b
            if z >= 0:
                total += ti * z + math.log1p(math.exp(-z))
            else:
                total += (ti - 1.0) * z + math.log1p(math.exp(z))
        return total

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> PlattCalibrator:
        _check_xy(scores, labels)
        n_pos = sum(1 for y in labels if y == 1)
        n_neg = len(labels) - n_pos
        if n_pos == 0 or n_neg == 0:
            raise CalibrationError("Platt scaling needs both classes")
        hi = (n_pos + 1.0) / (n_pos + 2.0)
        lo = 1.0 / (n_neg + 2.0)
        t = [hi if y == 1 else lo for y in labels]
        f = list(scores)
        a, b = 0.0, math.log((n_neg + 1.0) / (n_pos + 1.0))
        fval = self._objective(f, t, a, b)
        ridge = 1e-12
        for it in range(1, self.max_iter + 1):
            g1 = g2 = h11 = h22 = h21 = 0.0
            for fi, ti in zip(f, t, strict=True):
                p = _sigmoid_neg(a * fi + b)
                d = ti - p
                pq = p * (1.0 - p)
                g1 += fi * d
                g2 += d
                h11 += fi * fi * pq
                h22 += pq
                h21 += fi * pq
            h11 += ridge
            h22 += ridge
            if abs(g1) < self.tol and abs(g2) < self.tol:
                self.iterations = it - 1
                break
            det = h11 * h22 - h21 * h21
            if det <= 0:
                break
            da = -(h22 * g1 - h21 * g2) / det
            db = -(-h21 * g1 + h11 * g2) / det
            gd = g1 * da + g2 * db
            step = 1.0
            while step >= 1e-10:
                nfval = self._objective(f, t, a + step * da, b + step * db)
                if nfval < fval + 1e-4 * step * gd:
                    a += step * da
                    b += step * db
                    fval = nfval
                    break
                step /= 2.0
            else:
                break
            self.iterations = it
        self.a, self.b = a, b
        return self

    def transform(self, score: float) -> float:
        if self.a is None or self.b is None:
            raise CalibrationError("calibrator is not fitted")
        return _sigmoid_neg(self.a * _clip01(score) + self.b)

    def params(self) -> dict[str, Any]:
        if self.a is None or self.b is None:
            raise CalibrationError("calibrator is not fitted")
        return {"A": round(self.a, 12), "B": round(self.b, 12)}

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> PlattCalibrator:
        obj = cls()
        obj.a, obj.b = float(params["A"]), float(params["B"])
        if not (math.isfinite(obj.a) and math.isfinite(obj.b)):
            raise CalibrationError("invalid Platt parameters")
        return obj


# -------------------------------------------------------------------- isotonic
def pav(values: Sequence[float], weights: Sequence[float]) -> list[float]:
    """Weighted pool-adjacent-violators: the non-decreasing least-squares fit."""

    blocks: list[list[float]] = []  # [weighted mean, weight, count]
    for v, w in zip(values, weights, strict=True):
        blocks.append([v, w, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2, c2 = blocks.pop()
            m1, w1, c1 = blocks.pop()
            w = w1 + w2
            blocks.append([(m1 * w1 + m2 * w2) / w, w, c1 + c2])
    out: list[float] = []
    for mean, _w, count in blocks:
        out.extend([mean] * int(count))
    return out


class IsotonicCalibrator:
    method = METHOD_ISOTONIC

    def __init__(self) -> None:
        self.xs: list[float] | None = None
        self.ys: list[float] | None = None

    def fit(self, scores: Sequence[float], labels: Sequence[int]) -> IsotonicCalibrator:
        _check_xy(scores, labels)
        grouped: dict[float, list[float]] = {}
        for s, y in zip(scores, labels, strict=True):
            g = grouped.setdefault(s, [0.0, 0.0])
            g[0] += y
            g[1] += 1.0
        ux = sorted(grouped)
        means = [grouped[x][0] / grouped[x][1] for x in ux]
        wts = [grouped[x][1] for x in ux]
        fitted = pav(means, wts)
        xs: list[float] = []
        ys: list[float] = []
        i = 0
        while i < len(ux):  # keep only the end points of each constant block
            j = i
            while j + 1 < len(ux) and fitted[j + 1] == fitted[i]:
                j += 1
            xs.append(ux[i])
            ys.append(fitted[i])
            if j > i:
                xs.append(ux[j])
                ys.append(fitted[i])
            i = j + 1
        self.xs, self.ys = xs, ys
        return self

    def transform(self, score: float) -> float:
        if self.xs is None or self.ys is None:
            raise CalibrationError("calibrator is not fitted")
        s = _clip01(score)
        xs, ys = self.xs, self.ys
        if s <= xs[0]:
            return ys[0]
        if s >= xs[-1]:
            return ys[-1]
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= s:
                lo = mid
            else:
                hi = mid
        if xs[hi] == xs[lo]:
            return ys[hi]
        frac = (s - xs[lo]) / (xs[hi] - xs[lo])
        return ys[lo] + frac * (ys[hi] - ys[lo])

    def params(self) -> dict[str, Any]:
        if self.xs is None or self.ys is None:
            raise CalibrationError("calibrator is not fitted")
        return {
            "x": [round(x, 12) for x in self.xs],
            "y": [round(y, 12) for y in self.ys],
        }

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> IsotonicCalibrator:
        obj = cls()
        xs = [float(x) for x in params["x"]]
        ys = [float(y) for y in params["y"]]
        ok = (
            xs
            and len(xs) == len(ys)
            and all(a <= b for a, b in zip(xs, xs[1:], strict=False))
            and all(a <= b for a, b in zip(ys, ys[1:], strict=False))
            and all(0.0 <= y <= 1.0 for y in ys)
        )
        if not ok:
            raise CalibrationError("invalid isotonic parameters")
        obj.xs, obj.ys = xs, ys
        return obj


_FACTORIES: Mapping[str, type] = {
    METHOD_BINNING: BinningCalibrator,
    METHOD_PLATT: PlattCalibrator,
    METHOD_ISOTONIC: IsotonicCalibrator,
}


# --------------------------------------------------------------------- metrics
@dataclass(frozen=True)
class ReliabilityBin:
    low: float
    high: float
    count: int
    mean_score: float
    positive_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "count": self.count,
            "mean_score": round(self.mean_score, 6),
            "positive_rate": round(self.positive_rate, 6),
        }


def reliability_bins(
    scores: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> list[ReliabilityBin]:
    """Non-empty equal-width bins on [0, 1]; a score of 1.0 falls in the last bin."""

    _check_xy(scores, labels)
    if n_bins < 1:
        raise CalibrationError("n_bins must be >= 1")
    ssum = [0.0] * n_bins
    ysum = [0] * n_bins
    cnt = [0] * n_bins
    for s, y in zip(scores, labels, strict=True):
        b = min(n_bins - 1, int(s * n_bins))
        cnt[b] += 1
        ssum[b] += s
        ysum[b] += int(y)
    return [
        ReliabilityBin(
            i / n_bins, (i + 1) / n_bins, cnt[i], ssum[i] / cnt[i], ysum[i] / cnt[i]
        )
        for i in range(n_bins)
        if cnt[i]
    ]


def expected_calibration_error(
    scores: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> float:
    n = len(scores)
    bins = reliability_bins(scores, labels, n_bins)
    return sum(b.count / n * abs(b.positive_rate - b.mean_score) for b in bins)


def maximum_calibration_error(
    scores: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> float:
    return max(
        abs(b.positive_rate - b.mean_score)
        for b in reliability_bins(scores, labels, n_bins)
    )


def brier_score(scores: Sequence[float], labels: Sequence[int]) -> float:
    _check_xy(scores, labels)
    return sum((s - y) ** 2 for s, y in zip(scores, labels, strict=True)) / len(scores)


def reliability_report(
    scores: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> dict[str, Any]:
    """ECE / MCE / Brier / bins as a JSON-ready dict (measurement only)."""

    return {
        "n": len(scores),
        "n_positive": int(sum(labels)),
        "ece": round(expected_calibration_error(scores, labels, n_bins), 6),
        "mce": round(maximum_calibration_error(scores, labels, n_bins), 6),
        "brier": round(brier_score(scores, labels), 6),
        "bins": [b.to_dict() for b in reliability_bins(scores, labels, n_bins)],
    }


# -------------------------------------------------------------------- artifact
def _checksum(method: str, target: str, params: Mapping[str, Any]) -> str:
    blob = json.dumps(
        {"method": method, "target": target, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CalibrationArtifact:
    """A fitted calibrator as data: what is applied, to which score, fitted how.

    ``target`` says which score it calibrates (``criterion`` link confidence or
    ``chain`` score); the chain builder refuses a mismatched artifact. ``fit``
    carries caller-provided metadata (dataset id, n, split, metrics): the
    library records no clock or host information so artifacts are reproducible.
    """

    method: str
    target: str
    params: Mapping[str, Any]
    fit: Mapping[str, Any]
    version: str = CALIBRATION_ARTIFACT_VERSION
    source_algo_version: str = ""

    def calibrator(self) -> Calibrator:
        return _FACTORIES[self.method].from_params(self.params)  # type: ignore[attr-defined, no-any-return]

    @property
    def artifact_id(self) -> str:
        return _checksum(self.method, self.target, self.params)[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "method": self.method,
            "target": self.target,
            "source_algo_version": self.source_algo_version,
            "params": dict(self.params),
            "fit": dict(self.fit),
            "checksum": _checksum(self.method, self.target, self.params),
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationArtifact:
        if data.get("version") != CALIBRATION_ARTIFACT_VERSION:
            raise CalibrationError(
                f"unsupported artifact version {data.get('version')!r}"
            )
        method, target = data.get("method"), data.get("target")
        if method not in _FACTORIES:
            raise CalibrationError(f"unknown calibration method {method!r}")
        if target not in _TARGETS:
            raise CalibrationError(f"unknown calibration target {target!r}")
        params = dict(data["params"])
        if data.get("checksum") != _checksum(method, target, params):
            raise CalibrationError("artifact checksum mismatch")
        art = cls(
            method=method,
            target=target,
            params=params,
            fit=dict(data.get("fit", {})),
            version=data["version"],
            source_algo_version=data.get("source_algo_version", ""),
        )
        art.calibrator()  # validates the parameters
        return art

    @classmethod
    def from_json(cls, text: str) -> CalibrationArtifact:
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CalibrationError(f"malformed calibration artifact: {exc}") from exc


def fit_artifact(
    method: str,
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    target: str = TARGET_CRITERION,
    source_algo_version: str = "",
    dataset_id: str = "",
    n_bins: int = 10,
    extra: Mapping[str, Any] | None = None,
) -> CalibrationArtifact:
    """Fit ``method`` and record before/after reliability on the *fit* data.

    The recorded metrics are in-sample (optimistic); evaluate on held-out data
    before trusting a calibrator.
    """

    if method not in _FACTORIES:
        raise CalibrationError(f"unknown calibration method {method!r}")
    if target not in _TARGETS:
        raise CalibrationError(f"unknown calibration target {target!r}")
    cal = _FACTORIES[method]()
    cal.fit(scores, labels)
    after = [cal.transform(s) for s in scores]
    fit_meta: dict[str, Any] = {
        "dataset_id": dataset_id,
        "n": len(scores),
        "n_positive": int(sum(labels)),
        "in_sample": True,
        "ece_before": round(expected_calibration_error(scores, labels, n_bins), 6),
        "ece_after": round(expected_calibration_error(after, labels, n_bins), 6),
        "brier_before": round(brier_score(scores, labels), 6),
        "brier_after": round(brier_score(after, labels), 6),
    }
    fit_meta.update(extra or {})
    return CalibrationArtifact(
        method=method,
        target=target,
        params=cal.params(),
        fit=fit_meta,
        source_algo_version=source_algo_version,
    )
