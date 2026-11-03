"""Input validation shared by the calibration modules (stdlib only)."""

from __future__ import annotations

import math
from collections.abc import Sequence


class CalibrationInputError(ValueError):
    """Scores or labels are malformed (length, range, NaN, non-binary)."""


def check_scores_labels(
    scores: Sequence[float], labels: Sequence[int], *, allow_empty: bool = False
) -> tuple[list[float], list[int]]:
    """Return copies of ``scores`` (floats in [0, 1]) and ``labels`` (0 or 1).

    The label is 1 when the event the score predicts happened. Booleans are
    accepted.
    """

    if len(scores) != len(labels):
        raise CalibrationInputError(
            f"scores and labels differ in length ({len(scores)} vs {len(labels)})"
        )
    if not allow_empty and len(scores) == 0:
        raise CalibrationInputError("no data")
    out_s: list[float] = []
    out_y: list[int] = []
    for i, (s, y) in enumerate(zip(scores, labels, strict=True)):
        try:
            sf = float(s)
        except (TypeError, ValueError):
            raise CalibrationInputError(f"score {i} is not a number: {s!r}") from None
        if math.isnan(sf) or not 0.0 <= sf <= 1.0:
            raise CalibrationInputError(f"score {i} must be in [0, 1], got {s!r}")
        if y not in (0, 1):  # True == 1 and False == 0 pass
            raise CalibrationInputError(f"label {i} must be 0 or 1, got {y!r}")
        out_s.append(sf)
        out_y.append(int(y))
    return out_s, out_y
