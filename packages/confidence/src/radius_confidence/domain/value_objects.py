"""Confidence domain value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfidenceScore:
    """Confidence score in the inclusive 0..100 range."""

    value: float

    def __post_init__(self) -> None:
        if self.value < 0 or self.value > 100:
            msg = "Confidence score must be between 0 and 100."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CoveragePercent:
    """Coverage percentage in the inclusive 0..100 range."""

    value: float

    def __post_init__(self) -> None:
        if self.value < 0 or self.value > 100:
            msg = "Coverage percent must be between 0 and 100."
            raise ValueError(msg)
