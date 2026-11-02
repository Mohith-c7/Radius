"""Optional, default-off observability: correlation ids, tracing, metrics."""

from radius_shared.observability.context import (
    CORRELATION_KEYS,
    bind_correlation,
    get_correlation_context,
    update_correlation,
)
from radius_shared.observability.settings import ObservabilitySettings
from radius_shared.observability.stage import stage
from radius_shared.observability.tracing import (
    configure_tracing,
    continue_trace,
    current_trace_id,
    current_traceparent,
    reset_tracing,
    span,
)

__all__ = [
    "CORRELATION_KEYS",
    "ObservabilitySettings",
    "bind_correlation",
    "configure_tracing",
    "continue_trace",
    "current_trace_id",
    "current_traceparent",
    "get_correlation_context",
    "reset_tracing",
    "span",
    "stage",
    "update_correlation",
]
