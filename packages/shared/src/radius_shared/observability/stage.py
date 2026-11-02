"""Combined span + metric helper for pipeline stages."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from radius_shared.observability import metrics
from radius_shared.observability.tracing import span


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time a pipeline stage as a span and histogram; count failures."""

    started = time.perf_counter()
    try:
        with span(f"stage.{name}", **{"radius.stage": name}):
            yield
    except Exception:
        metrics.record_stage_failure(name)
        raise
    finally:
        metrics.observe_stage(name, time.perf_counter() - started)
