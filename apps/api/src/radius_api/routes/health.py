"""Health endpoints."""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_shared.dto import ApiResponse, error_response, success_response
from radius_shared.logging import get_logger
from sqlalchemy import text

from radius_api.config import get_api_settings

router = APIRouter(tags=["health"])
LOGGER = get_logger(__name__)


class HealthResponse(BaseModel):
    """Typed response returned by the health endpoint."""

    status: Literal["ok"]
    service: str
    environment: str
    storage: str


@router.get("/health", response_model=ApiResponse[HealthResponse])
def get_health() -> ApiResponse[HealthResponse]:
    """Return service health metadata."""

    settings = get_api_settings()
    return success_response(
        HealthResponse(
            status="ok",
            service=settings.service_name,
            environment=str(settings.environment),
            storage=settings.storage_backend,
        )
    )


@router.get("/ready", response_model=ApiResponse[HealthResponse])
def get_readiness(request: Request):
    """Return readiness after checking the database and the job queue.

    With SQL storage this runs ``select 1`` and reads the ``analysis_jobs``
    table (the durable queue). With memory storage the in-process queue is
    checked. Any failure yields 503 with the usual error envelope; the
    exception detail is logged, not returned.
    """

    settings = request.app.state.settings
    container = request.app.state.container
    try:
        if settings.storage_backend == "sql":
            if container.session_factory is None:
                msg = "SQL storage is not configured."
                raise RuntimeError(msg)
            with container.session_factory() as session:
                session.execute(text("select 1"))
                SqlAlchemyAnalysisJobQueue(session).depth_by_status()
        else:
            len(container.analysis_queue)
    except Exception as exc:
        LOGGER.error(
            "Readiness check failed",
            extra={"error": f"{exc.__class__.__name__}: {exc}"},
        )
        return JSONResponse(
            status_code=503,
            content=error_response(
                "not_ready", "A required dependency is unavailable."
            ).model_dump(),
        )
    return success_response(
        HealthResponse(
            status="ok",
            service=settings.service_name,
            environment=str(settings.environment),
            storage=settings.storage_backend,
        )
    )


def queue_depth_provider(container) -> Callable[[], dict[str, int]]:
    """Return a callable reporting jobs per status for the queue-depth gauge."""

    def provider() -> dict[str, int]:
        if container.session_factory is None:
            return {"pending": len(container.analysis_queue)}
        with container.session_factory() as session:
            return SqlAlchemyAnalysisJobQueue(session).depth_by_status()

    return provider
