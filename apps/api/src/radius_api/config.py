"""Application configuration for the Radius API."""

from functools import lru_cache
from uuid import UUID

from pydantic import Field
from radius_shared.database.session import DatabaseSettings


class ApiSettings(DatabaseSettings):
    """Runtime settings loaded from environment variables."""

    service_name: str = "radius-api"
    storage_backend: str = "memory"
    api_keys: str = ""
    github_webhook_secret: str = ""
    github_default_organization_id: UUID | None = None
    cors_origins: str = ""
    seed_demo_data: bool = Field(default=False, alias="RADIUS_SEED_DEMO_DATA")
    """Seed illustrative demo fixtures and a demo login at startup.

    Off by default and never honoured in production: the demo account uses a
    publicly documented password and the fixtures are not real analyses.
    """


@lru_cache
def get_api_settings() -> ApiSettings:
    """Return cached API settings."""

    return ApiSettings()
