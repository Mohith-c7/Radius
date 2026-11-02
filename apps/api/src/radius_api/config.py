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
    github_single_tenant: bool = Field(default=False, alias="GITHUB_SINGLE_TENANT")
    """Route webhooks from unknown installations to GITHUB_DEFAULT_ORGANIZATION_ID.

    Only safe when exactly one organization uses this GitHub App. When false
    (default), deliveries from installations not linked to an organization are
    rejected instead of being filed under the default organization.
    """
    intent_ingestion_enabled: bool = Field(
        default=False, alias="RADIUS_FEATURE_INTENT_INGESTION"
    )
    """IN-02: store PR title/body (and refreshed issue text) from webhook payloads.

    The API makes no GitHub API calls for this (it holds no App credentials); the
    worker fetches issues, commits and the spec file. OFF by default until the live
    GitHub validation (F-06) has happened; set true for that run.
    """
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
