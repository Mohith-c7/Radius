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
