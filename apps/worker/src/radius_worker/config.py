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
    analysis_deadline_seconds: int = Field(
        default=7200,
        alias="WORKER_ANALYSIS_DEADLINE_SECONDS",
        description=(
            "An analysis still pending/running this long after it started is "
            "failed by the reaper and its GitHub check completed. Keep it above "
            "WORKER_JOB_STALE_AFTER_SECONDS * WORKER_JOB_MAX_ATTEMPTS plus queue wait."
        ),
    )
    reaper_interval_seconds: float = Field(
        default=60.0,
        alias="WORKER_REAPER_INTERVAL_SECONDS",
    )
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

    # --- Test execution isolation (audit A#4 / P0-5) ---------------------
    # See docs/security/EXECUTION_ISOLATION.md and radius_worker.execution_mode.
    test_execution_mode: str | None = Field(
        default=None,
        alias="WORKER_TEST_EXECUTION_MODE",
        description=(
            "disabled (default) | sandbox | unsafe_in_process. Unset falls back "
            "to the legacy WORKER_EXECUTE_TESTS flag (true => unsafe_in_process)."
        ),
    )
    allow_unsafe_execution: bool = Field(
        default=False,
        alias="RADIUS_ALLOW_UNSAFE_EXECUTION",
        description=(
            "Required to use unsafe_in_process when RADIUS_ENV is uat or "
            "production. The worker refuses to start otherwise."
        ),
    )
    sandbox_runtime: str = Field(default="docker", alias="WORKER_SANDBOX_RUNTIME")
    sandbox_image: str = Field(
        default="python:3.12-slim",
        alias="WORKER_SANDBOX_IMAGE",
        description=(
            "Pre-provisioned image (pulled by operators; never fetched at "
            "analysis time) containing the test toolchain and dependencies."
        ),
    )
    sandbox_memory: str = Field(default="1g", alias="WORKER_SANDBOX_MEMORY")
    sandbox_cpus: str = Field(default="1.0", alias="WORKER_SANDBOX_CPUS")
    sandbox_pids_limit: int = Field(default=256, alias="WORKER_SANDBOX_PIDS_LIMIT")
    sandbox_tmpfs_size: str = Field(default="256m", alias="WORKER_SANDBOX_TMPFS_SIZE")
    sandbox_nofile_limit: int = Field(default=1024, alias="WORKER_SANDBOX_NOFILE_LIMIT")
    sandbox_max_file_size_bytes: int = Field(
        default=64 * 1024 * 1024, alias="WORKER_SANDBOX_MAX_FILE_SIZE_BYTES"
    )
    sandbox_max_output_bytes: int = Field(
        default=5 * 1024 * 1024,
        alias="WORKER_SANDBOX_MAX_OUTPUT_BYTES",
        description="Host-side cap on captured stdout/stderr; the container is killed past it.",
    )
    sandbox_seccomp_profile: str | None = Field(
        default=None,
        alias="WORKER_SANDBOX_SECCOMP_PROFILE",
        description=(
            "Optional path to a custom seccomp profile JSON. Unset keeps the "
            "runtime's default profile. 'unconfined' is rejected."
        ),
    )
