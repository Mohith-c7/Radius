"""Application configuration for the Radius API."""

import ipaddress
import re
from functools import lru_cache
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from radius_shared.config import RuntimeEnvironment
from radius_shared.database.session import DatabaseSettings
from radius_shared.verdict_v2_flag import VerdictV2Mode, parse_verdict_v2_mode

_RATE_SPEC = re.compile(r"^(\d{1,7})/(\d{1,6})$")


def parse_rate_spec(spec: str) -> tuple[int, int]:
    """Parse ``"<capacity>/<window_seconds>"`` into ``(capacity, window)``."""

    match = _RATE_SPEC.match(spec.strip())
    if match is None:
        msg = f"Invalid rate limit {spec!r}; expected '<requests>/<seconds>'."
        raise ValueError(msg)
    capacity, window = int(match.group(1)), int(match.group(2))
    if capacity < 1 or window < 1:
        msg = f"Invalid rate limit {spec!r}; both numbers must be >= 1."
        raise ValueError(msg)
    return capacity, window


def split_csv(value: str) -> list[str]:
    """Split a comma separated setting, dropping blanks."""

    return [item.strip() for item in value.split(",") if item.strip()]


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
    verdict_v2_mode: VerdictV2Mode = Field(
        default=VerdictV2Mode.OFF, alias="RADIUS_FEATURE_VERDICT_V2"
    )
    """Verdict v2 alpha flag: off (default), shadow or on (VD-07-lite).

    Off means no v2 code path runs and ``GET /analyses/{id}/verdict`` answers
    404 with ``meta.reason = disabled``. Unrecognised values are treated as off.
    """

    @field_validator("verdict_v2_mode", mode="before")
    @classmethod
    def _parse_verdict_v2_mode(cls, value: object) -> VerdictV2Mode:
        return parse_verdict_v2_mode(value)

    cors_origins: str = ""
    """Comma separated browser origins allowed by CORS (``CORS_ORIGINS``).

    Local dashboard origins are added automatically outside production. In
    production the list must be explicit: no ``*``, only ``https://`` origins.
    """
    cors_allow_credentials: bool = Field(
        default=True, alias="RADIUS_CORS_ALLOW_CREDENTIALS"
    )
    hsts_enabled: bool = Field(default=False, alias="RADIUS_HSTS_ENABLED")
    """Send Strict-Transport-Security. Enable only when served over TLS."""
    hsts_max_age: int = Field(default=31536000, ge=0, alias="RADIUS_HSTS_MAX_AGE")
    max_body_bytes: int = Field(
        default=1024 * 1024, ge=1024, alias="RADIUS_MAX_BODY_BYTES"
    )
    webhook_max_body_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1024, alias="RADIUS_WEBHOOK_MAX_BODY_BYTES"
    )
    upload_max_body_bytes: int = Field(
        default=20 * 1024 * 1024, ge=1024, alias="RADIUS_UPLOAD_MAX_BODY_BYTES"
    )
    trusted_proxies: str = Field(default="", alias="RADIUS_TRUSTED_PROXIES")
    """Comma separated IPs/CIDRs of reverse proxies whose X-Forwarded-For is trusted."""
    rate_limit_enabled: bool = Field(default=True, alias="RADIUS_RATE_LIMIT_ENABLED")
    rate_limit_auth: str = Field(default="10/60", alias="RADIUS_RATE_LIMIT_AUTH")
    rate_limit_webhook: str = Field(default="600/60", alias="RADIUS_RATE_LIMIT_WEBHOOK")
    rate_limit_general: str = Field(default="600/60", alias="RADIUS_RATE_LIMIT_GENERAL")
    rate_limit_expensive: str = Field(
        default="20/60", alias="RADIUS_RATE_LIMIT_EXPENSIVE"
    )
    rate_limit_ip_multiplier: int = Field(
        default=2, ge=1, le=100, alias="RADIUS_RATE_LIMIT_IP_MULTIPLIER"
    )
    """Per-IP limit = per-key limit x this, for key-identified buckets."""
    seed_demo_data: bool = Field(default=False, alias="RADIUS_SEED_DEMO_DATA")
    """Seed illustrative demo fixtures and a demo login at startup.

    Off by default and never honoured in production: the demo account uses a
    publicly documented password and the fixtures are not real analyses.
    """

    @field_validator(
        "rate_limit_auth",
        "rate_limit_webhook",
        "rate_limit_general",
        "rate_limit_expensive",
    )
    @classmethod
    def _valid_rate(cls, value: str) -> str:
        parse_rate_spec(value)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _valid_proxies(cls, value: str) -> str:
        for item in split_csv(value):
            ipaddress.ip_network(item, strict=False)
        return value

    @model_validator(mode="after")
    def _validate_http_hardening(self) -> "ApiSettings":
        production = self.environment == RuntimeEnvironment.PRODUCTION
        for origin in split_csv(self.cors_origins):
            if origin == "*":
                if production:
                    msg = "CORS_ORIGINS must not contain '*' in production."
                    raise ValueError(msg)
                continue
            if not re.match(r"^https?://[^/\s*]+$", origin):
                msg = f"CORS origin {origin!r} must look like https://host[:port]."
                raise ValueError(msg)
            if production and not origin.startswith("https://"):
                msg = f"CORS origin {origin!r} must use https:// in production."
                raise ValueError(msg)
        return self


@lru_cache
def get_api_settings() -> ApiSettings:
    """Return cached API settings."""

    return ApiSettings()
