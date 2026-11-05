"""API wiring for correlation ids, tracing and metrics (all optional)."""

from __future__ import annotations

import hmac
import re
import time
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request, Response
from radius_shared.logging import get_logger
from radius_shared.observability import (
    ObservabilitySettings,
    bind_correlation,
    configure_tracing,
    span,
)
from radius_shared.observability import metrics as obs_metrics
from starlette.middleware.base import BaseHTTPMiddleware

LOGGER = get_logger(__name__)
REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

router = APIRouter(tags=["observability"])


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Bind a request id, open the request span, echo the id to the client."""

    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if _SAFE_REQUEST_ID.match(supplied) else uuid4().hex
        started = time.perf_counter()
        with (
            bind_correlation(request_id=request_id),
            span(
                "http.request",
                **{
                    "http.method": request.method,
                    "http.target": request.url.path,
                },
            ) as current,
        ):
            response = await call_next(request)
            if current is not None:
                current.set_attribute("http.status_code", response.status_code)
        response.headers[REQUEST_ID_HEADER] = request_id
        LOGGER.debug(
            "Request handled",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "request_id": request_id,
            },
        )
        return response


@router.get("/metrics", include_in_schema=False)
def get_metrics(request: Request) -> Response:
    """Prometheus exposition; 404 unless ``RADIUS_METRICS_ENABLED`` is set.

    With ``RADIUS_METRICS_TOKEN`` the caller must send ``Authorization: Bearer
    <token>``. Without a token the endpoint is open only in development/test and
    off in uat/production (A-16): metrics expose route names and traffic shape.
    """

    if not obs_metrics.metrics_enabled():
        return Response(status_code=404)
    token = getattr(request.app.state, "metrics_token", "")
    if token:
        presented = request.headers.get("Authorization", "")
        scheme, _, credential = presented.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            credential.encode("utf-8"), token.encode("utf-8")
        ):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    else:
        env = str(getattr(getattr(request.app.state, "settings", None), "environment", ""))
        if env.rsplit(".", 1)[-1].lower() in {"production", "uat"}:
            return Response(status_code=404)
    payload, content_type = obs_metrics.render_metrics()
    return Response(content=payload, media_type=content_type)


def configure_api_observability(app: FastAPI, settings: ObservabilitySettings) -> None:
    """Install middleware and, when enabled, tracing and metrics."""

    if settings.service_name == "radius":
        settings = settings.model_copy(update={"service_name": "radius-api"})
    configure_tracing(settings)
    obs_metrics.configure_metrics(settings.metrics_enabled)
    app.state.metrics_token = settings.metrics_token
    app.add_middleware(CorrelationMiddleware)
    app.include_router(router)
