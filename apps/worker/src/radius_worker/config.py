"""Worker runtime configuration."""

from pathlib import Path

from pydantic import Field, field_validator
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
    execute_tests: bool = Field(
        default=False,
        alias="WORKER_EXECUTE_TESTS",
        description=(
            "Run selected tests inside the worker. Disabled by default: the "
            "tests are pull-request-controlled code and the worker process holds "
            "database and GitHub App credentials. Enable only when the worker "
            "runs in an isolated sandbox with no credentials; otherwise run the "
            "selected tests in CI and upload JUnit results."
        ),
    )
    test_timeout_seconds: int = Field(default=600, alias="WORKER_TEST_TIMEOUT_SECONDS")
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

    @field_validator("github_installation_id", mode="before")
    @classmethod
    def _parse_installation_id(cls, v):
        if v is None or v == "" or v == 0 or v == "0":
            return None
        return int(v)

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
