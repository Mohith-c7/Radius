"""Runtime configuration loaded from environment variables."""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./radius.db"
    session_secret: str = Field(min_length=32)
    frontend_origin: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    session_cookie_secure: bool = False
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None
    email_delivery_mode: str = "console"


@lru_cache
def get_settings() -> Settings:
    return Settings()
