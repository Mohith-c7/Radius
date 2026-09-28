"""FastAPI entrypoint for Radius."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from radius_shared.dto import error_response
from radius_shared.errors import (
    AccessDeniedError,
    ConflictError,
    NotFoundError,
    RadiusError,
    ValidationError,
)
from radius_shared.logging import configure_logging

from radius_api.config import get_api_settings
from radius_api.dependencies import AppContainer, configure_sql_storage
from radius_api.routes.analyses import router as analyses_router
from radius_api.routes.confidence import router as confidence_router
from radius_api.routes.github_webhooks import router as github_webhooks_router
from radius_api.routes.graph import router as graph_router
from radius_api.routes.health import router as health_router
from radius_api.routes.repositories import router as repositories_router
from radius_api.routes.tests import router as tests_router

# Authentication remains implemented in the existing application auth module.
# Register it on this package-managed entrypoint so the dashboard and the
# development command use the same auth system and persistent token store.
from app.database import Base as AuthBase
from app.database import engine as auth_engine
from app.routes_auth import router as auth_router


async def radius_error_handler(
    request: Request,
    exc: RadiusError,
) -> JSONResponse:
    """Convert expected application errors into API envelopes."""

    status_code = 400
    if isinstance(exc, AccessDeniedError):
        status_code = 403
    elif isinstance(exc, ConflictError):
        status_code = 409
    elif isinstance(exc, NotFoundError):
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
    allow_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    if settings.cors_origins:
        allow_origins.extend([o.strip() for o in settings.cors_origins.split(",") if o.strip()])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.container = AppContainer()
    if settings.storage_backend == "sql":
        configure_sql_storage(app.state.container, settings)
    app.add_exception_handler(RadiusError, radius_error_handler)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(repositories_router, prefix="/api/v1")
    app.include_router(analyses_router, prefix="/api/v1")
    app.include_router(graph_router, prefix="/api/v1")
    app.include_router(tests_router, prefix="/api/v1")
    app.include_router(confidence_router, prefix="/api/v1")
    app.include_router(github_webhooks_router, prefix="/api/v1")
    app.include_router(auth_router)

    @app.on_event("startup")
    def initialize_auth_database() -> None:
        """Create the tables used by the shared authentication implementation."""

        AuthBase.metadata.create_all(bind=auth_engine)

    return app


app = create_app()
