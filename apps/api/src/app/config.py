"""Runtime configuration loaded from environment variables."""
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

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


PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), extra="ignore", populate_by_name=True)
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
