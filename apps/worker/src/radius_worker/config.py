"""Worker runtime configuration."""

from pathlib import Path

from pydantic import Field
from radius_shared.database.session import DatabaseSettings


class WorkerSettings(DatabaseSettings):
    """Runtime settings loaded from environment variables."""

    service_name: str = "radius-worker"
    repository_cache_dir: Path = Field(
        default=Path(".radius/repositories"),
        alias="REPOSITORY_CACHE_DIR",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        alias="WORKER_POLL_INTERVAL_SECONDS",
    )
    job_stale_after_seconds: int = Field(
        default=1800,
        alias="WORKER_JOB_STALE_AFTER_SECONDS",
    )
    job_max_attempts: int = Field(default=3, alias="WORKER_JOB_MAX_ATTEMPTS")
    dashboard_base_url: str = Field(default="", alias="DASHBOARD_BASE_URL")
    github_publish_results: bool = Field(
        default=True,
        alias="GITHUB_PUBLISH_RESULTS",
    )
    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_installation_id: int | None = Field(
        default=None,
        alias="GITHUB_INSTALLATION_ID",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        alias="GITHUB_API_BASE_URL",
    )
    github_api_version: str = Field(
        default="2026-03-10",
        alias="GITHUB_API_VERSION",
    )
    github_timeout_seconds: float = Field(
        default=10.0,
        alias="GITHUB_TIMEOUT_SECONDS",
    )
