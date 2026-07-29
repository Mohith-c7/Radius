"""Shared configuration primitives."""

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeEnvironment(StrEnum):
    """Supported Radius runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    UAT = "uat"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported structured logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RadiusBaseSettings(BaseSettings):
    """Base settings shared by Radius services."""

    environment: RuntimeEnvironment = Field(
        default=RuntimeEnvironment.DEVELOPMENT,
        alias="RADIUS_ENV",
    )
    log_level: LogLevel = Field(default=LogLevel.INFO, alias="RADIUS_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
