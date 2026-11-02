"""Optional Prometheus metrics.

Disabled by default. Until :func:`configure_metrics` enables them (and
``prometheus_client`` is installed) every recording function is a no-op, so
instrumented code needs no conditionals.

Metrics use a private registry so repeated configuration in tests never
raises duplicate-registration errors.

Label values are deliberately low-cardinality (stage names, outcomes); ids
such as analysis or org ids are never used as labels.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )
    from prometheus_client.core import GaugeMetricFamily

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on installed extras
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

QueueDepthProvider = Callable[[], dict[str, int]]


class _Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.job_duration = Histogram(
            "radius_job_duration_seconds",
            "Wall-clock duration of one analysis job attempt.",
            ["outcome"],
            buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800),
            registry=self.registry,
        )
        self.stage_duration = Histogram(
            "radius_stage_duration_seconds",
            "Duration of one pipeline stage.",
            ["stage"],
            buckets=(0.01, 0.05, 0.25, 1, 5, 30, 120, 600),
            registry=self.registry,
        )
        self.stage_failures = Counter(
            "radius_stage_failures_total",
            "Pipeline stage failures.",
            ["stage"],
            registry=self.registry,
        )
        self.job_retries = Counter(
            "radius_job_retries_total",
            "Job attempts returned to the queue for another try.",
            registry=self.registry,
        )
        self.sandbox_kills = Counter(
            "radius_sandbox_kills_total",
            "Sandboxed test containers killed (for example on timeout).",
            ["reason"],
            registry=self.registry,
        )
        self.llm_cost = Counter(
            "radius_llm_cost_usd_total",
            "PLACEHOLDER: LLM spend in USD. Nothing records to it yet.",
            registry=self.registry,
        )
        self.queue_depth_provider: QueueDepthProvider | None = None
        self.registry.register(_QueueDepthCollector(self))


class _QueueDepthCollector:
    """Computes queue depth at scrape time so it is never stale."""

    def __init__(self, owner: _Metrics) -> None:
        self._owner = owner

    def describe(self):
        return []

    def collect(self):
        family = GaugeMetricFamily(
            "radius_queue_depth",
            "Analysis jobs by status.",
            labels=["status"],
        )
        provider = self._owner.queue_depth_provider
        if provider is not None:
            try:
                for status, count in provider().items():
                    family.add_metric([status], count)
            except Exception:  # a broken DB must not break the scrape
                family.add_metric(["unavailable"], 1)
        yield family


_LOCK = threading.Lock()
_METRICS: _Metrics | None = None


def configure_metrics(enabled: bool) -> bool:
    """Enable (fresh registry) or disable metrics; return the resulting state."""

    global _METRICS
    with _LOCK:
        if not enabled or not PROMETHEUS_AVAILABLE:
            _METRICS = None
            return False
        _METRICS = _Metrics()
        return True


def metrics_enabled() -> bool:
    return _METRICS is not None


def set_queue_depth_provider(provider: QueueDepthProvider | None) -> None:
    """Register a callable returning ``{status: count}`` for the depth gauge."""

    if _METRICS is not None:
        _METRICS.queue_depth_provider = provider


def start_metrics_server(port: int) -> None:
    """Serve metrics on ``port`` (worker process); ``0`` or disabled is a no-op."""

    if _METRICS is None or not port:
        return
    from prometheus_client import start_http_server

    start_http_server(port, registry=_METRICS.registry)


def render_metrics() -> tuple[bytes, str]:
    """Return the exposition payload and its content type."""

    if _METRICS is None:
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(_METRICS.registry), CONTENT_TYPE_LATEST


def observe_job(duration_seconds: float, outcome: str) -> None:
    if _METRICS is not None:
        _METRICS.job_duration.labels(outcome).observe(duration_seconds)


def observe_stage(stage: str, duration_seconds: float) -> None:
    if _METRICS is not None:
        _METRICS.stage_duration.labels(stage).observe(duration_seconds)


def record_stage_failure(stage: str) -> None:
    if _METRICS is not None:
        _METRICS.stage_failures.labels(stage).inc()


def record_retry() -> None:
    if _METRICS is not None:
        _METRICS.job_retries.inc()


def record_sandbox_kill(reason: str = "timeout") -> None:
    if _METRICS is not None:
        _METRICS.sandbox_kills.labels(reason).inc()


def record_llm_cost(usd: float) -> None:
    """Placeholder hook; no LLM call site reports cost yet."""

    if _METRICS is not None:
        _METRICS.llm_cost.inc(usd)
