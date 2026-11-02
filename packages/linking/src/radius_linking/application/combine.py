"""Link combination (LK-02 baseline; LK-06 will refine).

For one (criterion, symbol) pair with per-linker scores ``s_i`` in [0, 1] and a
change-kind prior ``p`` in [0, 1]::

    base  = 1 - prod_i (1 - w_i * s_i)            # weighted noisy-OR
    final = base * (1 - k + k * p)                # prior scales evidence, k = prior_strength
    final = min(final, cap)                       # 0.99 with explicit evidence, else 0.95

``w_i`` are configurable linker weights (defaults: explicit 1.0, identifier 0.9,
lexical 0.8, structural 0.6) and ``k`` defaults to 0.5. Properties (tested):
bounded in [0, 1]; monotone non-decreasing in every ``s_i`` and in ``p``; zero
evidence gives zero; order of linkers is irrelevant. The prior never *creates* a
link, it only scales existing evidence. The noisy-OR treats linkers as
independent, which they are not (all read the same names), so scores are
rank-calibrated at best; LK-06 owns calibration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from radius_linking.domain import (
    LINKER_EXPLICIT,
    LINKER_IDENTIFIER,
    LINKER_LEXICAL,
    LINKER_STRUCTURAL,
)

COMBINER_VERSION = "noisy-or-prior-v1"

DEFAULT_WEIGHTS: Mapping[str, float] = {
    LINKER_EXPLICIT: 1.0,
    LINKER_IDENTIFIER: 0.9,
    LINKER_LEXICAL: 0.8,
    LINKER_STRUCTURAL: 0.6,
}


@dataclass(frozen=True)
class CombineConfig:
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    prior_strength: float = 0.5
    cap_explicit: float = 0.99
    cap_other: float = 0.95
    min_score: float = 0.01
    top_k: int = 10

    def __post_init__(self) -> None:
        for name, w in self.weights.items():
            if not 0.0 <= w <= 1.0:
                raise ValueError(f"weight for {name!r} must be in [0, 1]")
        if not 0.0 <= self.prior_strength <= 1.0:
            raise ValueError("prior_strength must be in [0, 1]")
        if not 0.0 <= self.cap_other <= self.cap_explicit <= 1.0:
            raise ValueError("require 0 <= cap_other <= cap_explicit <= 1")
        if not 0.0 <= self.min_score < 1.0:
            raise ValueError("min_score must be in [0, 1)")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": dict(sorted(self.weights.items())),
            "prior_strength": self.prior_strength,
            "cap_explicit": self.cap_explicit,
            "cap_other": self.cap_other,
            "min_score": self.min_score,
            "top_k": self.top_k,
            "combiner": COMBINER_VERSION,
        }


def combine_scores(
    scores: Mapping[str, float], prior: float, cfg: CombineConfig
) -> float:
    """Combine per-linker scores and a prior into one final score (see module docs)."""

    miss = 1.0
    for name, s in scores.items():
        w = cfg.weights.get(name, 0.0)
        miss *= 1.0 - w * min(1.0, max(0.0, s))
    base = 1.0 - miss
    k = cfg.prior_strength
    final = base * (1.0 - k + k * min(1.0, max(0.0, prior)))
    cap = cfg.cap_explicit if scores.get(LINKER_EXPLICIT, 0.0) > 0 else cfg.cap_other
    return min(final, cap)
