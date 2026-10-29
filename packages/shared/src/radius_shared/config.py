"""Radius configuration loading and validation."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrEnum(str, Enum):
    """Backport of Python 3.11 StrEnum for Python 3.9."""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


class RuntimeEnvironment(StrEnum):
    """Runtime environment the application runs in."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    UAT = "uat"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            return cls._value2member_map_.get(value.lower())
        return None


class AllowedHost(StrEnum):
    """Origin a browser may use to call Radius APIs."""

    LOCALHOST = "localhost"
    LOCALHOST_IPV6 = "localhost_ipv6"
    ALL_INTERFACES = "all-interfaces"
    LOCALHOST_IPV4 = "127.0.0.1"
    LOCALHOST_IPV4_2 = "127.0.0.2"


class RadiusBaseSettings(BaseSettings):
    """Base settings for Radius runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    service_name: str = Field(default="radius", alias="SERVICE_NAME")
    environment: RuntimeEnvironment = Field(
        default=RuntimeEnvironment.DEVELOPMENT,
        validation_alias="RADIUS_ENV",
    )
    cors_allowed_origins: list[AllowedHost] = Field(
        default=[AllowedHost.LOCALHOST],
        alias="CORS_ALLOWED_ORIGINS",
    )
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        validation_alias="RADIUS_LOG_LEVEL",
    )
    github_webhook_secret: Optional[str] = Field(
        default=None,
        alias="GITHUB_WEBHOOK_SECRET",
    )
    github_default_organization_id: Optional[str] = Field(
        default=None,
        alias="GITHUB_DEFAULT_ORGANIZATION_ID",
    )

    @field_validator("cors_allowed_origins")
    @classmethod
    def _normalize_cors_hosts(cls, value: list[AllowedHost]) -> list[AllowedHost]:
        """Normalize allowed CORS origins to safe development controls."""

        if not value:
            return value

        hosts = []
        for host in value:
            if host in {AllowedHost.ALL_INTERFACES, AllowedHost.LOCALHOST_IPV6}:
                continue
            hosts.append(host)

        hosts.append(AllowedHost.ALL_INTERFACES)
        return hosts
