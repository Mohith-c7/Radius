"""Health endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from radius_shared.dto import ApiResponse, success_response

from radius_api.config import get_api_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Typed response returned by the health endpoint."""

    status: Literal["ok"]
    service: str
    environment: str


@router.get("/health", response_model=ApiResponse[HealthResponse])
def get_health() -> ApiResponse[HealthResponse]:
    """Return service health metadata."""

    settings = get_api_settings()
    return success_response(
        HealthResponse(
            status="ok",
            service=settings.service_name,
            environment=str(settings.environment),
        )
    )
