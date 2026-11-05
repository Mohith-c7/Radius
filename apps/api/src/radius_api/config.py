"""Application configuration for the Radius API."""

import ipaddress
import re
from functools import lru_cache
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator
from radius_repository.domain.clone_url import GitUrlPolicy, parse_allowed_hosts
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
    """DEPRECATED legacy ``org_id:key`` entries (full access). See docs/security/API_KEYS.md."""
    api_key_pepper: str = Field(default="", alias="RADIUS_API_KEY_PEPPER")
    """Server-side secret mixed into managed-key fingerprints (>= 32 chars).

    Without it managed keys are disabled (legacy ``API_KEYS`` still work).
    """
    api_key_last_used_interval_seconds: int = Field(
        default=300, ge=0, alias="RADIUS_API_KEY_LAST_USED_INTERVAL"
    )
    """Minimum seconds between ``last_used_at`` writes for one key."""
    github_webhook_secret: str = ""
    github_default_organization_id: UUID | None = None
    github_single_tenant: bool = Field(default=False, alias="GITHUB_SINGLE_TENANT")
    """Route webhooks from unknown installations to GITHUB_DEFAULT_ORGANIZATION_ID.

    Only safe when exactly one organization uses this GitHub App. When false
    (default), deliveries from installations not linked to an organization are
    rejected instead of being filed under the default organization.
    """
    git_allowed_hosts: str = Field(
        default="github.com",
        alias="RADIUS_GIT_ALLOWED_HOSTS",
        description=(
            "Comma separated hosts a repository clone URL may name (https only, "
            "`https://<host>/<owner>/<repo>[.git]`). Default `github.com`; set your "
            "GitHub Enterprise Server host to use it instead. Clone URLs on any other "
            "host are refused at the API and again by the worker, and the GitHub "
            "installation token is never sent to a host that is not listed."
        ),
    )
    github_dev_single_tenant: bool | None = Field(
        default=None,
        alias="RADIUS_GITHUB_DEV_SINGLE_TENANT",
        description=(
            "Single-tenant development mode for `POST /repositories/connect-github`: "
            "when true an organization with no GitHub installation may adopt the "
            "installation the App has on the requested repository. Default: true when "
            "`RADIUS_ENV=development`, false otherwise. Never enable it on a deployment "
            "where more than one organization uses the App: any caller could then attach "
            "another customer's installation."
        ),
    )
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

    Off means no v2 code path runs and ``GET /analyses/{id}/verdict-v2`` answers
    404 with ``meta.reason = disabled``. Unrecognised values are treated as off.
    """

    @field_validator("verdict_v2_mode", mode="before")
    @classmethod
    def _parse_verdict_v2_mode(cls, value: object) -> VerdictV2Mode:
        return parse_verdict_v2_mode(value)

    cors_origins: str = Field(
        default="",
        validation_alias=AliasChoices("CORS_ORIGINS", "CORS_ALLOW_ORIGINS", "cors_origins"),
    )
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
        default=5 * 1024 * 1024, ge=1024, alias="RADIUS_WEBHOOK_MAX_BODY_BYTES"
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

    @field_validator("api_key_pepper")
    @classmethod
    def _valid_pepper(cls, value: str) -> str:
        if value and len(value) < 32:
            msg = "RADIUS_API_KEY_PEPPER must be at least 32 characters."
            raise ValueError(msg)
        return value

    @field_validator("git_allowed_hosts")
    @classmethod
    def _valid_git_hosts(cls, value: str) -> str:
        parse_allowed_hosts(value)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _valid_proxies(cls, value: str) -> str:
        for item in split_csv(value):
            ipaddress.ip_network(item, strict=False)
        return value

    @model_validator(mode="after")
    def _resolve_dev_single_tenant(self) -> "ApiSettings":
        if self.github_dev_single_tenant is None:
            self.github_dev_single_tenant = (
                self.environment == RuntimeEnvironment.DEVELOPMENT
            )
        return self

    @property
    def git_url_policy(self) -> GitUrlPolicy:
        """Clone URL policy built from ``RADIUS_GIT_ALLOWED_HOSTS``."""

        return GitUrlPolicy(allowed_hosts=parse_allowed_hosts(self.git_allowed_hosts))

    @model_validator(mode="after")
    def _require_api_credentials(self) -> "ApiSettings":
        """A-09: uat/production needs some way to authenticate API callers."""

        if self.environment in {RuntimeEnvironment.PRODUCTION, RuntimeEnvironment.UAT} and (
            not self.api_key_pepper and not split_csv(self.api_keys)
        ):
            msg = (
                "Set RADIUS_API_KEY_PEPPER (managed API keys, preferred) or API_KEYS "
                "(deprecated static keys) when RADIUS_ENV is uat or production: "
                "otherwise no API caller can authenticate."
            )
            raise ValueError(msg)
        return self

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
