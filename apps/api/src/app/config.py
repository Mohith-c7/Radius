"""Runtime configuration loaded from environment variables."""
import logging
import os
import re
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Session secrets that are published in this repository; never valid in production.
KNOWN_PUBLIC_SESSION_SECRETS = frozenset(
    {
        "super_secret_radius_session_key_32bytes_min",
        "your_secure_random_session_secret_min_32_chars",
    }
)
EMAIL_DELIVERY_MODES = ("smtp", "log")
_DNS_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
LOGGER = logging.getLogger(__name__)


def _csv(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _dns_name(value: str) -> bool:
    labels = value.split(".")
    return len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    runtime_env: str = Field(default="development", alias="RADIUS_ENV")
    database_url: str = "sqlite:///./radius.db"
    session_secret: str = Field(default="super_secret_radius_session_key_32bytes_min", min_length=32)
    frontend_origin: str = "http://127.0.0.1:3000"
    session_cookie_secure: bool = False
    session_cookie_domain: str | None = None
    """Optional ``Domain`` of the session cookie (C-20), for example ``example.com`` when the
    dashboard (``app.example.com``) and the API (``api.example.com``) are separate hosts. Unset
    (default) keeps a host-only cookie, which needs one origin or localhost."""
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None
    email_delivery_mode: str = "smtp"
    """``smtp`` (default) sends mail; ``log`` writes the message and its link to the API log (local dev only)."""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    signup_allowed_emails: str = Field(default="", alias="RADIUS_SIGNUP_ALLOWED_EMAILS")
    """Comma-separated e-mail addresses allowed to use the dashboard (exact match, case-insensitive). When this
    or `RADIUS_SIGNUP_ALLOWED_DOMAINS` is set, any other address cannot sign up with a password, cannot be
    provisioned or signed in through Google/GitHub, cannot sign in with a password and loses its existing
    sessions. Empty with an empty domain list (default): everyone may sign up. Recommended for any public URL."""
    signup_allowed_domains: str = Field(default="", alias="RADIUS_SIGNUP_ALLOWED_DOMAINS")
    """Comma-separated e-mail domains allowed to use the dashboard, matched exactly against the part after `@`
    (`example.com` does not admit `team.example.com`; list each subdomain). Same effect as
    `RADIUS_SIGNUP_ALLOWED_EMAILS`; an address is allowed when either list matches."""

    default_organization_id: str | None = Field(default=None, alias="RADIUS_DEFAULT_ORGANIZATION_ID")
    """Single-tenant deployments: UUID of the one organization every signed-in user belongs to (normally the
    same value as `GITHUB_DEFAULT_ORGANIZATION_ID` and the dashboard's `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID`).
    A new user joins it instead of getting a personal workspace. An existing user whose organization is an
    auto-created personal workspace with no repositories, no GitHub installation and no other member is moved
    into it at the next sign-in; anyone else is left where they are and the API logs it. The organization must
    exist (`python -m radius_api.bootstrap`); when it does not, sign-in logs an error and keeps the old
    behaviour. Unset (default): every new user gets a personal workspace (multi-tenant behaviour)."""
    admin_emails: str = Field(default="", alias="RADIUS_ADMIN_EMAILS")
    """Comma-separated e-mail addresses (exact match, case-insensitive) that get the admin role in
    `RADIUS_DEFAULT_ORGANIZATION_ID` when they sign in with a verified address. Everyone else keeps their role
    (new users are developers); an existing admin is never demoted automatically. Ignored (with a startup
    warning) without `RADIUS_DEFAULT_ORGANIZATION_ID`."""

    @staticmethod
    def _address_list(value: str, name: str) -> str:
        entries = _csv(value or "")
        for entry in entries:
            local, at, domain = entry.rpartition("@")
            if not at or not local or "@" in local or any(c.isspace() for c in entry) or not _dns_name(domain):
                msg = f"{name} entries must be full addresses such as alice@example.com."
                raise ValueError(msg)
        return ",".join(dict.fromkeys(entries))

    @field_validator("signup_allowed_emails")
    @classmethod
    def _valid_allowed_emails(cls, value: str) -> str:
        return cls._address_list(value, "RADIUS_SIGNUP_ALLOWED_EMAILS")

    @field_validator("admin_emails")
    @classmethod
    def _valid_admin_emails(cls, value: str) -> str:
        return cls._address_list(value, "RADIUS_ADMIN_EMAILS")

    @field_validator("default_organization_id")
    @classmethod
    def _valid_default_organization(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return str(UUID(value.strip()))
        except ValueError as exc:
            msg = "RADIUS_DEFAULT_ORGANIZATION_ID must be an organization UUID."
            raise ValueError(msg) from exc

    def is_admin_email(self, email: str) -> bool:
        """True when ``email`` is on ``RADIUS_ADMIN_EMAILS``; the caller checks it is verified."""
        return email.strip().lower() in _csv(self.admin_emails)

    @field_validator("signup_allowed_domains")
    @classmethod
    def _valid_allowed_domains(cls, value: str) -> str:
        entries = [entry.rstrip(".") for entry in _csv(value or "")]
        for entry in entries:
            if "@" in entry or not _dns_name(entry):
                msg = (
                    "RADIUS_SIGNUP_ALLOWED_DOMAINS entries must be domains such as example.com "
                    "(no '@', no wildcard)."
                )
                raise ValueError(msg)
        return ",".join(dict.fromkeys(entries))

    @property
    def signup_allowlist_enabled(self) -> bool:
        return bool(self.signup_allowed_emails or self.signup_allowed_domains)

    def email_allowed(self, email: str) -> bool:
        """R7: True when no allowlist is configured or ``email`` matches one of the lists."""
        if not self.signup_allowlist_enabled:
            return True
        address = email.strip().lower()
        if address in _csv(self.signup_allowed_emails):
            return True
        _, at, domain = address.rpartition("@")
        return bool(at) and domain in _csv(self.signup_allowed_domains)

    @field_validator("session_cookie_domain")
    @classmethod
    def _valid_cookie_domain(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        domain = value.strip().lower().lstrip(".")
        labels = domain.split(".")
        if (
            len(labels) < 2
            or any(not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
            or re.fullmatch(r"[0-9.]+", domain)
        ):
            msg = "SESSION_COOKIE_DOMAIN must be a registrable DNS name such as example.com (no IP address, port or scheme)."
            raise ValueError(msg)
        return domain

    @field_validator("email_delivery_mode")
    @classmethod
    def _valid_delivery_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in EMAIL_DELIVERY_MODES:
            msg = f"EMAIL_DELIVERY_MODE must be one of {', '.join(EMAIL_DELIVERY_MODES)}."
            raise ValueError(msg)
        return mode

    @model_validator(mode="after")
    def _production_like_guards(self) -> "Settings":
        """Controls that must hold in production AND uat (A-09, A-16)."""
        if self.runtime_env.strip().lower() not in {"production", "uat"}:
            return self
        if not self.session_cookie_secure:
            msg = (
                "SESSION_COOKIE_SECURE must be true when RADIUS_ENV is production or uat: "
                "the session and OAuth flow cookies would otherwise travel over plain HTTP."
            )
            raise ValueError(msg)
        if os.environ.get("DEV_AUTO_VERIFY_EMAIL", "").strip().lower() in {"true", "1", "yes"}:
            msg = (
                "DEV_AUTO_VERIFY_EMAIL marks every signup as verified and is refused "
                "when RADIUS_ENV is production or uat."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.runtime_env.strip().lower() != "production":
            return self
        if self.session_secret in KNOWN_PUBLIC_SESSION_SECRETS:
            msg = "SESSION_SECRET is a published placeholder; set a random value (>= 32 chars) in production."
            raise ValueError(msg)
        if self.email_delivery_mode == "log":
            msg = "EMAIL_DELIVERY_MODE=log writes sign-in links to the logs and is not allowed in production."
            raise ValueError(msg)
        for name, uri in (
            ("GOOGLE_REDIRECT_URI", self.google_redirect_uri),
            ("GITHUB_REDIRECT_URI", self.github_redirect_uri),
        ):
            if uri and urlsplit(uri).scheme != "https":
                msg = f"{name} must be an https URL in production."
                raise ValueError(msg)
        if not self.signup_allowlist_enabled:
            # Not refused (existing deployments would stop), but loud: see docs/operations/HARDENING.md.
            LOGGER.warning(
                "RADIUS_ENV=production without RADIUS_SIGNUP_ALLOWED_EMAILS or RADIUS_SIGNUP_ALLOWED_DOMAINS: "
                "anyone who can reach the dashboard can sign up and act on the configured organization."
            )
        return self

    @model_validator(mode="after")
    def _admin_emails_need_default_org(self) -> "Settings":
        if self.admin_emails and not self.default_organization_id:
            LOGGER.warning(
                "RADIUS_ADMIN_EMAILS is set without RADIUS_DEFAULT_ORGANIZATION_ID and is ignored: "
                "admin roles are only granted in the default organization."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
