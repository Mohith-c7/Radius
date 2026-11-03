"""Selective risk, abstention thresholds and their finite-sample statements.

Stdlib only. Conventions: ``confidence`` is the score used to decide;
``correct`` is 1 when the system's positive call (accept) would be right and 0
when accepting would be an error. A threshold ``t`` accepts items with
``confidence >= t`` and abstains (``needs_review``) on the rest. A decision
whose ``threshold`` is ``None`` accepts nothing: **with too little data the
procedures abstain more, never accept more.**

Two procedures, deliberately separate because they bound different risks:

* :func:`ltt_threshold` (Learn-then-Test style, Bonferroni over a fixed grid,
  Clopper-Pearson p-values): bounds the **accepted-set error rate**
  ``P(incorrect | accepted) <= alpha`` with probability ``>= 1 - delta`` over
  the calibration draw. This is the quantity PREREGISTRATION 7.1 calls "error
  among accepted".
* :func:`crc_threshold` (conformal risk control, ``Angelopoulos2024crc``) with
  the loss ``1[incorrect and accepted]``: bounds the **joint** false-accept rate
  ``P(accepted and incorrect) <= alpha`` in expectation. That is a different
  and weaker-for-the-user quantity: the accepted-set error is that joint rate
  divided by coverage, so it can exceed alpha.

The preregistration draft's shifted loss ``(1[incorrect] - alpha) * 1[accepted]``
is *not* non-increasing in the threshold per item (a correct, accepted item has
loss ``-alpha`` that rises to 0 as the threshold passes it), which the CRC
theorem requires. :func:`find_nonincreasing_violation` demonstrates this on
data; whether and how to repair it is a decision for the owner/implementer
before freeze (CA-05 / PREREGISTRATION 7.1), not something this module settles.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ._validate import CalibrationInputError, check_scores_labels
from .intervals import clopper_pearson_upper

DEFAULT_GRID: tuple[float, ...] = tuple(i / 100 for i in range(101))


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    threshold: float
    n_accepted: int
    n_errors: int
    coverage: float
    risk: float | None  # None when nothing is accepted

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "n_accepted": self.n_accepted,
            "n_errors": self.n_errors,
            "coverage": self.coverage,
            "risk": self.risk,
        }


def risk_coverage_curve(
    confidence: Sequence[float], correct: Sequence[int]
) -> list[RiskCoveragePoint]:
    """Selective risk against coverage, one point per distinct confidence value.

    Thresholds are the distinct scores in descending order, so coverage grows
    along the list; items tied at a score are accepted together. ``risk`` is the
    error rate among accepted items.
    """

    cs, ok = check_scores_labels(confidence, correct, allow_empty=True)
    n = len(cs)
    order = sorted(range(n), key=lambda i: -cs[i])
    points: list[RiskCoveragePoint] = []
    accepted = errors = 0
    i = 0
    while i < n:
        t = cs[order[i]]
        while i < n and cs[order[i]] == t:
            accepted += 1
            errors += 1 - ok[order[i]]
            i += 1
        points.append(RiskCoveragePoint(t, accepted, errors, accepted / n, errors / accepted))
    return points


def evaluate_threshold(
    confidence: Sequence[float],
    correct: Sequence[int],
    threshold: float | None,
    *,
    delta: float = 0.05,
) -> dict:
    """Realised accepted-set error of a fixed threshold on (held-out) data.

    Returns counts, coverage, the observed error rate and the exact one-sided
    Clopper-Pearson upper bound at ``1 - delta``. Use only on data that was not
    used to choose the threshold.
    """

    cs, ok = check_scores_labels(confidence, correct, allow_empty=True)
    n = len(cs)
    if threshold is None:
        acc = 0
        err = 0
    else:
        acc = sum(1 for c in cs if c >= threshold)
        err = sum(1 - y for c, y in zip(cs, ok, strict=True) if c >= threshold)
    return {
        "threshold": threshold,
        "n": n,
        "n_accepted": acc,
        "n_errors": err,
        "coverage": acc / n,
        "error_rate": (err / acc) if acc else None,
        "error_upper_bound": clopper_pearson_upper(err, acc, delta) if acc else None,
        "bound_confidence": 1.0 - delta,
    }


@dataclass(frozen=True, slots=True)
class ThresholdDecision:
    method: str
    risk_kind: str
    alpha: float
    delta: float | None
    threshold: float | None
    n_cal: int
    n_accepted_cal: int
    errors_cal: int
    upper_bound: float | None
    guarantee: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    @property
    def abstains_on_everything(self) -> bool:
        return self.threshold is None

    @property
    def coverage_cal(self) -> float:
        return self.n_accepted_cal / self.n_cal if self.n_cal else 0.0

    @property
    def empirical_risk_cal(self) -> float | None:
        return self.errors_cal / self.n_accepted_cal if self.n_accepted_cal else None

    def accepts(self, confidence: float) -> bool:
        return self.threshold is not None and confidence >= self.threshold

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "risk_kind": self.risk_kind,
            "alpha": self.alpha,
            "delta": self.delta,
            "threshold": self.threshold,
            "abstains_on_everything": self.abstains_on_everything,
            "n_cal": self.n_cal,
            "n_accepted_cal": self.n_accepted_cal,
            "errors_cal": self.errors_cal,
            "coverage_cal": self.coverage_cal,
            "empirical_risk_cal": self.empirical_risk_cal,
            "upper_bound": self.upper_bound,
            "guarantee": self.guarantee,
            "assumptions": list(self.assumptions),
            "note": self.note,
        }


_LTT_GUARANTEE = (
    "With probability >= 1 - delta over the draw of the calibration set, the "
    "population error rate among accepted items, P(incorrect | confidence >= t), "
    "is <= alpha for the selected t (simultaneously valid for every t on the "
    "grid; Bonferroni over the grid, exact binomial p-values). If no grid "
    "threshold can be certified the decision abstains on everything."
)
_LTT_ASSUMPTIONS = (
    "calibration items and future items are i.i.d. draws from one distribution "
    "(no covariate, label or temporal shift)",
    "the threshold grid was fixed before looking at the calibration labels",
    "labels are correct (label noise is not modelled)",
    "the statement is about the population rate, not about any single item",
)
_CRC_GUARANTEE = (
    "If the n calibration items and the new item are exchangeable, the expected "
    "joint false-accept rate E[1{incorrect and confidence >= t}] is <= alpha for "
    "the selected t. This bounds the probability of accepting an incorrect item "
    "among ALL items, not the error rate among accepted items (that equals this "
    "rate divided by coverage and may exceed alpha). The expectation is also over "
    "the calibration draw, so it is an average guarantee, not a per-dataset one."
)
_CRC_ASSUMPTIONS = (
    "calibration items and the new item are exchangeable (no distribution shift)",
    "loss 1[incorrect and accepted] is non-increasing in t and bounded by 1",
    "labels are correct (label noise is not modelled)",
)


def _check_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise CalibrationInputError("alpha must be in (0, 1)")


def ltt_threshold(
    confidence: Sequence[float],
    correct: Sequence[int],
    alpha: float,
    delta: float = 0.10,
    grid: Sequence[float] = DEFAULT_GRID,
) -> ThresholdDecision:
    """Pick the lowest grid threshold whose accepted-set error is certified <= alpha.

    For each grid value ``t`` the null "error rate among items with
    confidence >= t exceeds alpha" is tested with the exact one-sided
    Clopper-Pearson bound at level ``delta / len(grid)``; ``t`` is certified when
    the bound is <= alpha. The lowest certified ``t`` (largest coverage) is
    returned. The grid must be fixed independently of the labels.
    """

    _check_alpha(alpha)
    if not 0.0 < delta < 1.0:
        raise CalibrationInputError("delta must be in (0, 1)")
    gv = sorted({float(g) for g in grid})
    if not gv:
        raise CalibrationInputError("grid must not be empty")
    cs, ok = check_scores_labels(confidence, correct, allow_empty=True)
    n = len(cs)
    corrected = delta / len(gv)
    chosen: tuple[float, int, int, float] | None = None
    for t in gv:
        acc = [y for c, y in zip(cs, ok, strict=True) if c >= t]
        if not acc:
            continue
        k = len(acc) - sum(acc)
        if k / len(acc) > alpha:  # observed risk already above alpha: cannot certify
            continue
        ub = clopper_pearson_upper(k, len(acc), corrected)
        if ub <= alpha:
            chosen = (t, len(acc), k, ub)
            break
    if chosen is None:
        return ThresholdDecision(
            "ltt-bonferroni", "accepted_set_error", alpha, delta, None, n, 0, 0, None,
            _LTT_GUARANTEE, _LTT_ASSUMPTIONS,
            note="no threshold could be certified: abstain on everything",
        )
    t, n_acc, k, ub = chosen
    return ThresholdDecision(
        "ltt-bonferroni", "accepted_set_error", alpha, delta, t, n, n_acc, k, ub,
        _LTT_GUARANTEE, _LTT_ASSUMPTIONS,
    )


def crc_threshold(
    confidence: Sequence[float], correct: Sequence[int], alpha: float
) -> ThresholdDecision:
    """Conformal risk control for the loss ``1[incorrect and confidence >= t]``.

    Picks the smallest ``t`` among the distinct calibration scores such that
    ``n/(n+1) * Rhat(t) + 1/(n+1) <= alpha`` (loss bound B = 1). If none
    qualifies (for example ``n + 1 < 1/alpha``) it abstains on everything. See
    the module docstring for what this does and does not bound.
    """

    _check_alpha(alpha)
    cs, ok = check_scores_labels(confidence, correct, allow_empty=True)
    n = len(cs)
    order = sorted(range(n), key=lambda i: cs[i])
    sorted_c = [cs[i] for i in order]
    sorted_err = [1 - ok[i] for i in order]
    suffix_err = [0] * (n + 1)
    for j in range(n - 1, -1, -1):
        suffix_err[j] = suffix_err[j + 1] + sorted_err[j]
    chosen: tuple[float, int, int] | None = None
    j = 0
    while j < n:
        t = sorted_c[j]
        errs = suffix_err[j]
        if (n / (n + 1)) * (errs / n) + 1.0 / (n + 1) <= alpha:
            chosen = (t, n - j, errs)
            break
        while j < n and sorted_c[j] == t:
            j += 1
    if chosen is None:
        return ThresholdDecision(
            "crc-joint", "joint_false_accept_rate", alpha, None, None, n, 0, 0, None,
            _CRC_GUARANTEE, _CRC_ASSUMPTIONS,
            note="no threshold satisfies the CRC condition: abstain on everything",
        )
    t, n_acc, errs = chosen
    return ThresholdDecision(
        "crc-joint", "joint_false_accept_rate", alpha, None, t, n, n_acc, errs,
        (n / (n + 1)) * (errs / n) + 1.0 / (n + 1),
        _CRC_GUARANTEE, _CRC_ASSUMPTIONS,
        note="upper_bound is the CRC-adjusted empirical joint risk, not an accepted-set error bound",
    )


def prereg_shifted_loss(confidence: float, correct: int, threshold: float, alpha: float) -> float:
    """PREREGISTRATION 7.1 loss: ``(1[incorrect] - alpha) * 1[accepted at t]``."""

    return ((1 - correct) - alpha) * (1.0 if confidence >= threshold else 0.0)


def find_nonincreasing_violation(
    loss: Callable[[int, float], float],
    n_items: int,
    thresholds: Sequence[float],
    tol: float = 1e-12,
) -> dict | None:
    """First (item, t_lo < t_hi) with ``loss(item, t_hi) > loss(item, t_lo)``, else None.

    CRC requires every item's loss to be non-increasing in the threshold. A
    returned dict is a concrete counterexample for the supplied data.
    """

    ts = sorted(thresholds)
    for i in range(n_items):
        prev = loss(i, ts[0])
        for t_lo, t_hi in zip(ts, ts[1:], strict=False):
            cur = loss(i, t_hi)
            if cur > prev + tol:
                return {
                    "item": i,
                    "t_lo": t_lo,
                    "t_hi": t_hi,
                    "loss_lo": prev,
                    "loss_hi": cur,
                }
            prev = cur
    return None
