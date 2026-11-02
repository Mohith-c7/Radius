"""Circuit breaker and backoff (clock and sleeper are injectable)."""

from __future__ import annotations

from collections.abc import Callable


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; one trial call after ``cooldown_s``."""

    def __init__(
        self,
        threshold: int,
        cooldown_s: float,
        clock: Callable[[], float],
    ) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at >= self._cooldown:
            # half-open: allow a trial; a failure re-opens immediately
            self._failures = self._threshold - 1
            self._opened_at = None
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


def backoff_delay(attempt: int, base_s: float, max_s: float) -> float:
    """Deterministic exponential backoff (no jitter) after the n-th failed attempt."""

    return min(max_s, base_s * (2 ** (attempt - 1)))
