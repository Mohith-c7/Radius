"""Application configuration for the Radius API."""

from functools import lru_cache

from radius_shared.config import RadiusBaseSettings


class ApiSettings(RadiusBaseSettings):
    """Runtime settings loaded from environment variables."""

    service_name: str = "radius-api"


@lru_cache
def get_api_settings() -> ApiSettings:
    """Return cached API settings."""

    return ApiSettings()
