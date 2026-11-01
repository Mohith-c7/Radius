"""Health endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from radius_shared.dto import ApiResponse, success_response
from sqlalchemy import text

from radius_api.config import get_api_settings

router = APIRouter(tags=["health"])


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
def get_readiness(request: Request) -> ApiResponse[HealthResponse]:
    """Return readiness metadata after checking configured dependencies."""

    settings = request.app.state.settings
    container = request.app.state.container
    if settings.storage_backend == "sql":
        if container.session_factory is None:
            msg = "SQL storage is not configured."
            raise RuntimeError(msg)
        with container.session_factory() as session:
            session.execute(text("select 1"))
    return success_response(
        HealthResponse(
            status="ok",
            service=settings.service_name,
            environment=str(settings.environment),
            storage=settings.storage_backend,
        )
    )
