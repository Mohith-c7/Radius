"""Optional OpenTelemetry tracing.

OpenTelemetry is an optional dependency and tracing is off by default. When it
is unavailable or disabled every helper here is a cheap no-op, so callers can
wrap code in :func:`span` unconditionally.

Trace context crosses the job queue through a *carrier*: the W3C
``traceparent`` captured at enqueue time and persisted in
``analysis_jobs.traceparent`` so it survives process boundaries.
:class:`TraceCarrierStore` is a legacy in-process helper, no longer used by the
queue. See docs/OBSERVABILITY.md.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from radius_shared.observability.context import get_correlation_context
from radius_shared.observability.settings import ObservabilitySettings

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on installed extras
    OTEL_AVAILABLE = False

LOGGER = logging.getLogger(__name__)
_TRACER_NAME = "radius"
_propagator = TraceContextTextMapPropagator() if OTEL_AVAILABLE else None
#: Radius' own provider. The global OpenTelemetry provider is deliberately not
#: replaced, so embedding apps keep control and tests can reconfigure freely.
_PROVIDER: Any | None = None


def configure_tracing(
    settings: ObservabilitySettings | None = None,
    *,
    span_exporter: Any | None = None,
    provider: Any | None = None,
) -> bool:
    """Install a tracer provider when tracing is enabled; return whether it was.

    ``span_exporter`` lets tests supply an in-memory exporter. With no exporter
    and no ``RADIUS_OTLP_ENDPOINT`` spans are recorded but not exported.
    """

    settings = settings or ObservabilitySettings()
    if not settings.tracing_enabled and span_exporter is None:
        return False
    if not OTEL_AVAILABLE:
        LOGGER.warning(
            "RADIUS_TRACING_ENABLED is set but opentelemetry is not installed; "
            "tracing stays disabled. Install the 'observability' extra."
        )
        return False

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SimpleSpanProcessor,
    )

    provider = provider or TracerProvider(
        resource=Resource.create({"service.name": settings.service_name})
    )
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )
    global _PROVIDER
    _PROVIDER = provider
    return True


def reset_tracing() -> None:
    """Drop the configured provider (tracing becomes a no-op again)."""

    global _PROVIDER
    if _PROVIDER is not None and hasattr(_PROVIDER, "shutdown"):
        _PROVIDER.shutdown()
    _PROVIDER = None


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Run a block inside a span (no-op without OpenTelemetry).

    Correlation ids currently bound are attached as ``radius.<key>``
    attributes. Exceptions are recorded and the span marked as errored.
    """

    if not OTEL_AVAILABLE or _PROVIDER is None:
        yield None
        return
    tracer = _PROVIDER.get_tracer(_TRACER_NAME)
    attrs = {f"radius.{k}": v for k, v in get_correlation_context().items()}
    attrs.update({k: v for k, v in attributes.items() if v is not None})
    with tracer.start_as_current_span(name, attributes=attrs) as current:
        yield current


def current_traceparent() -> str | None:
    """Return the active span's W3C ``traceparent`` or ``None``."""

    if not OTEL_AVAILABLE or _PROVIDER is None:
        return None
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def current_trace_id() -> str | None:
    """Return the active trace id as 32 hex chars, if a span is recording."""

    if not OTEL_AVAILABLE:
        return None
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


@contextmanager
def continue_trace(traceparent: str | None) -> Iterator[None]:
    """Make spans started inside the block children of ``traceparent``."""

    if not OTEL_AVAILABLE or not traceparent:
        yield
        return
    try:
        ctx = _propagator.extract({"traceparent": traceparent})
        token = otel_context.attach(ctx)
    except Exception:  # malformed carrier: fall back to a fresh trace
        LOGGER.debug("Ignoring invalid traceparent")
        yield
        return
    try:
        yield
    finally:
        otel_context.detach(token)
