"""The ``Calibrator`` hook point and the states a calibrated number can be in.

Nothing in the product imports this module. Verdict v2 is uncalibrated and
stays so (``calibrated: false`` in every payload, ``docs/verdict-v2.md``). This
is the interface a future CA-03/CA-04 integration would implement, behind the
VD-07 flag, so that the integration point is decided before there is data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class CalibrationState(StrEnum):
    """What may be said about a number.

    ``UNCALIBRATED_PRIOR``: no calibrator was fitted (too few labels, or none
    exist). The value is a heuristic or benchmark prior and must be displayed
    as such (DESIGN 6.7: "uncalibrated prior" until ``n_labels`` passes a
    minimum).

    ``FITTED``: a calibrator was fitted on at least the declared minimum N. This
    is only a statement about the fit's sample size; it says nothing about
    calibration quality on new data, which must be measured on held-out labels
    (``evaluate_calibration``) and is never implied by this state.
    """

    UNCALIBRATED_PRIOR = "uncalibrated_prior"
    FITTED = "fitted"


@dataclass(frozen=True, slots=True)
class CalibratedScore:
    """A raw score mapped through a calibrator, with provenance."""

    value: float
    state: CalibrationState
    kind: str
    n_fit: int
    raw: float

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "state": self.state.value,
            "kind": self.kind,
            "n_fit": self.n_fit,
            "raw": self.raw,
        }


@runtime_checkable
class Calibrator(Protocol):
    """Maps a raw score in [0, 1] to a probability estimate.

    Implementations must be deterministic and side-effect free once built, and
    must report honestly through ``state`` whether they were fitted. A
    calibrator is never allowed to raise a score's apparent certainty without
    a ``FITTED`` state.
    """

    kind: str
    state: CalibrationState
    n_fit: int

    def calibrate(self, raw: float) -> CalibratedScore: ...

    def calibrate_many(self, raw: Sequence[float]) -> list[CalibratedScore]: ...
