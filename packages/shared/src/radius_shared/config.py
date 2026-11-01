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
    allow_insecure_dev: bool = Field(
        default=False,
        alias="RADIUS_ALLOW_INSECURE_DEV",
        description=(
            "Explicit opt-in to accept unsigned GitHub webhooks and API calls "
            "without configured API keys. Honoured only in development/test; "
            "ignored in every other environment."
        ),
    )

    @property
    def insecure_dev_mode(self) -> bool:
        """Return whether missing auth secrets may be tolerated (fail closed)."""

        return self.allow_insecure_dev and self.environment in {
            RuntimeEnvironment.DEVELOPMENT,
            RuntimeEnvironment.TEST,
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
