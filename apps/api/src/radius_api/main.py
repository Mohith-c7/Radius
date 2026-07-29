"""FastAPI entrypoint for Radius."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from radius_shared.dto import error_response
from radius_shared.errors import NotFoundError, RadiusError, ValidationError
from radius_shared.logging import configure_logging

from radius_api.config import get_api_settings
from radius_api.dependencies import AppContainer
from radius_api.routes.analyses import router as analyses_router
from radius_api.routes.confidence import router as confidence_router
from radius_api.routes.graph import router as graph_router
from radius_api.routes.health import router as health_router
from radius_api.routes.repositories import router as repositories_router
from radius_api.routes.tests import router as tests_router


async def radius_error_handler(
    request: Request,
    exc: RadiusError,
) -> JSONResponse:
    """Convert expected application errors into API envelopes."""

    status_code = 400
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ValidationError):
        status_code = 422
    return JSONResponse(
        status_code=status_code,
        content=error_response(
            exc.detail.code,
            exc.detail.message,
        ).model_dump(),
    )


def create_app() -> FastAPI:
    """Create and configure the Radius API application."""

    settings = get_api_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Radius API",
        version="0.1.0",
        description="Software verification API for Radius.",
    )
    app.state.settings = settings
    app.state.container = AppContainer()
    app.add_exception_handler(RadiusError, radius_error_handler)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(repositories_router, prefix="/api/v1")
    app.include_router(analyses_router, prefix="/api/v1")
    app.include_router(graph_router, prefix="/api/v1")
    app.include_router(tests_router, prefix="/api/v1")
    app.include_router(confidence_router, prefix="/api/v1")
    return app


app = create_app()
