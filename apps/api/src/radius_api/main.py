"""FastAPI entrypoint for Radius."""

from fastapi import FastAPI

from radius_api.config import get_api_settings
from radius_api.routes.health import router as health_router


def create_app() -> FastAPI:
    """Create and configure the Radius API application."""

    settings = get_api_settings()
    app = FastAPI(
        title="Radius API",
        version="0.1.0",
        description="Software verification API for Radius.",
    )
    app.state.settings = settings
    app.include_router(health_router, prefix="/api/v1")
    return app


app = create_app()
