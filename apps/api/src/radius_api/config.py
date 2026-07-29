"""Application configuration for the Radius API."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    environment: str = Field(default="development", alias="RADIUS_ENV")
    service_name: str = "radius-api"
    log_level: str = Field(default="INFO", alias="RADIUS_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_api_settings() -> ApiSettings:
    """Return cached API settings."""

    return ApiSettings()
