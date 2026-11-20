"""Call budget, pacing, deadline and retries around any :class:`LlmProvider`.

Free LLM tiers are rate limited per minute and per day, and the worker runs on a tiny
instance, so every provider built by :func:`radius_intent.infrastructure.llm.factory.build_llm_provider`
is wrapped in :class:`GuardedProvider`:

* **Per-analysis call budget.** One wrapper is built per feature and analysis; it makes at
  most ``max_calls`` calls (retries count; the model fallbacks and the JSON re-ask inside
  one call of the OpenAI-compatible adapter do not, but they do pass the gate below).
* **Process-wide pacing and daily cap** (:class:`RateGate`): calls are spaced by at least
  ``min_interval_s`` and at most ``max_per_day`` calls are made in any rolling 24 hours.
  The counters live in memory, so a restart resets them (documented in ``docs/ai.md``).
* **Deadline.** A wrapper built with ``deadline_s`` never starts a call, a wait or a retry
  that would end after the deadline; each call's timeout is cut to the time left.
* **Retries with backoff** on retryable errors (timeout, 429, 5xx), honouring the
  provider's ``Retry-After`` when present. The error that ends the retries is re-raised as
  non-retryable, so a caller with its own retry loop does not multiply the calls.

Any refusal raises a :class:`ProviderError`; callers already treat that as "no LLM output"
and keep their deterministic result.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from radius_intent.infrastructure.llm.provider import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    ProviderBudgetExhausted,
    ProviderError,
    ProviderTimeout,
)
from radius_intent.infrastructure.llm.resilience import backoff_delay

DAY_S = 86_400.0
#: Never start a call with less time than this left before the deadline.
MIN_CALL_WINDOW_S = 1.0


class RateGate:
    """Process-wide pacing (minimum spacing) and a rolling 24-hour call cap. Thread-safe."""

    def __init__(
        self,
        min_interval_s: float,
        max_per_day: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = max(0.0, float(min_interval_s))
        self._max_day = max(0, int(max_per_day))
        self._clock = clock
        self._lock = threading.Lock()
        self._next_free = 0.0
        self._recent: deque[float] = deque()

    def reserve(self, max_wait_s: float | None) -> float:
        """Reserve the next call slot and return how long to wait before using it.

        Raises :class:`ProviderBudgetExhausted` when the daily cap is reached or the wait
        would exceed ``max_wait_s``; nothing is reserved then.
        """

        with self._lock:
            now = self._clock()
            while self._recent and now - self._recent[0] >= DAY_S:
                self._recent.popleft()
            if self._max_day and len(self._recent) >= self._max_day:
                raise ProviderBudgetExhausted("daily LLM call cap reached")
            start = max(now, self._next_free)
            wait = start - now
            if max_wait_s is not None and wait > max_wait_s:
                raise ProviderBudgetExhausted("pacing wait exceeds the deadline")
            self._next_free = start + self._interval
            self._recent.append(start)
            return wait

    @property
    def calls_last_day(self) -> int:
        with self._lock:
            return len(self._recent)


def _final(exc: ProviderError) -> ProviderError:
    exc.retryable = False  # instance attribute: the caller must not retry again
    return exc


class GuardedProvider:
    """Wraps a provider with the budget, pacing, deadline and retry policy above."""

    def __init__(
        self,
        inner: LlmProvider,
        *,
        gate: RateGate,
        max_calls: int | None = None,
        deadline_s: float | None = None,
        max_attempts: int = 2,
        timeout_cap_s: float | None = None,
        backoff_base_s: float = 2.0,
        backoff_max_s: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._max_calls = max_calls
        self._clock = clock
        self._sleep = sleeper
        self._deadline = None if deadline_s is None else clock() + max(0.0, deadline_s)
        self._max_attempts = max(1, int(max_attempts))
        self._timeout_cap = timeout_cap_s
        self._base = backoff_base_s
        self._cap = backoff_max_s
        self.calls = 0
        # An adapter that makes several HTTP requests per call (model fallback, JSON
        # re-ask) reserves a gate slot before each one, so pacing and the daily cap count
        # real requests; otherwise one slot is reserved per call here.
        self._per_http = hasattr(inner, "before_http")
        if self._per_http:
            inner.before_http = self._reserve  # type: ignore[attr-defined]

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def last_model(self) -> str | None:
        """The model that produced the last reply (fallback lists), else ``model_id``."""

        return getattr(self._inner, "last_model", None) or self._inner.model_id

    def _reserve(self) -> None:
        remaining = self.remaining_s()
        wait = self._gate.reserve(None if remaining is None else remaining - MIN_CALL_WINDOW_S)
        if wait > 0:
            self._sleep(wait)

    @property
    def inner(self) -> LlmProvider:
        return self._inner

    def remaining_s(self) -> float | None:
        return None if self._deadline is None else self._deadline - self._clock()

    def complete(self, request: LlmRequest) -> LlmResponse:
        for attempt in range(1, self._max_attempts + 1):
            remaining = self.remaining_s()
            if remaining is not None and remaining <= MIN_CALL_WINDOW_S:
                raise _final(ProviderTimeout("LLM deadline reached"))
            if self._max_calls is not None and self.calls >= self._max_calls:
                raise _final(ProviderBudgetExhausted("per-analysis LLM call budget used"))
            if not self._per_http:
                self._reserve()
            remaining = self.remaining_s()
            timeout = request.timeout_s
            if self._timeout_cap is not None:
                timeout = min(timeout, self._timeout_cap)
            if remaining is not None:
                timeout = min(timeout, remaining)
            self.calls += 1
            try:
                return self._inner.complete(replace(request, timeout_s=max(0.5, timeout)))
            except ProviderError as exc:
                if not exc.retryable or attempt == self._max_attempts:
                    raise _final(exc) from None
                delay = (
                    exc.retry_after_s
                    if exc.retry_after_s is not None
                    else backoff_delay(attempt, self._base, self._cap)
                )
                remaining = self.remaining_s()
                if delay > self._cap or (
                    remaining is not None and delay >= remaining - MIN_CALL_WINDOW_S
                ):
                    raise _final(exc) from None
                self._sleep(delay)
        raise _final(ProviderBudgetExhausted("no attempt left"))  # pragma: no cover


__all__ = ["GuardedProvider", "MIN_CALL_WINDOW_S", "RateGate"]
