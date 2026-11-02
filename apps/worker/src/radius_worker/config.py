"""Worker runtime configuration."""

from pathlib import Path

from pydantic import Field, field_validator
from radius_shared.database.session import DatabaseSettings
from radius_shared.verdict_v2_flag import VerdictV2Mode, parse_verdict_v2_mode


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
    symbol_impact_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_SYMBOL_IMPACT",
        description=(
            "F-08: narrow test selection and blast radius to tests that can reach "
            "the changed Python symbols. Falls back to file-level impact whenever "
            "symbol information is missing or low-confidence."
        ),
    )
    symbol_changes_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_SYMBOL_CHANGES",
        description=(
            "LK-01: extract the changed symbols (function/method/class, with change "
            "kinds) for the diff and log their counts. Nothing is persisted yet "
            "(LK-05); failures never affect the analysis."
        ),
    )
    coverage_contexts_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_COVERAGE_CONTEXTS",
        description=(
            "LK-03: allow the dynamic coverage-context symbol-to-test linker, which "
            "runs the selected tests under coverage.py inside the hardened sandbox "
            "(never on the worker host). Off by default; not wired into the "
            "pipeline until LK-05, so it only gates the library entry point."
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

    # --- Intent source ingestion (IN-02) -----------------------------------
    intent_ingestion_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_INTENT_INGESTION",
        description=(
            "IN-02 (OFF until the live F-06 validation): when a GitHub App is configured, fetch the PR title/body, "
            "linked issues, commit messages and .radius/intent.yml for each new "
            "analysis and build the intent snapshot. Best-effort: a failure is "
            "logged and never fails the analysis. Linked issues need the App's "
            "'issues: read' permission (a missing permission is recorded as an "
            "absent source, not an error)."
        ),
    )
    verdict_v2_mode: VerdictV2Mode = Field(
        default=VerdictV2Mode.OFF,
        alias="RADIUS_FEATURE_VERDICT_V2",
        description=(
            "Verdict v2 alpha (VD-07-lite): off (default) runs no v2 code; shadow "
            "computes and stores v2 but still publishes v1; on publishes v2 when "
            "it succeeded and falls back to v1 otherwise. true/1 mean on; "
            "unrecognised values mean off. Needs RADIUS_FEATURE_INTENT_INGESTION "
            "for a useful result."
        ),
    )

    @field_validator("verdict_v2_mode", mode="before")
    @classmethod
    def _parse_verdict_v2_mode(cls, value: object) -> VerdictV2Mode:
        return parse_verdict_v2_mode(value)

    intent_max_api_calls: int = Field(
        default=15,
        ge=1,
        le=50,
        alias="RADIUS_INTENT_MAX_API_CALLS",
        description="Hard cap on GitHub REST calls per analysis for intent ingestion.",
    )
    intent_deadline_seconds: float = Field(
        default=30.0,
        gt=0,
        alias="RADIUS_INTENT_DEADLINE_SECONDS",
        description="Wall-clock budget for all intent ingestion calls of one analysis.",
    )
    intent_allow_cross_repo: bool = Field(
        default=False,
        alias="RADIUS_INTENT_ALLOW_CROSS_REPO",
        description=(
            "Fetch issues named by closing references in OTHER repositories "
            "(owner/repo#n, issue URLs). Off by default: the installation token "
            "can read every repository of the installation, so honoring a link "
            "written by a PR author would expose that repository's issue text. "
            "Skipped links are recorded as absent (cross_repo_disabled)."
        ),
    )
    intent_include_issue_comments: bool = Field(
        default=False,
        alias="RADIUS_INTENT_INCLUDE_ISSUE_COMMENTS",
        description=(
            "Also fetch comments on linked issues and keep only those written by "
            "OWNER/MEMBER/COLLABORATOR humans, as separate 'comment' sources. "
            "Costs one extra API call per linked issue that has comments."
        ),
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
    test_reruns: int = Field(
        default=0,
        ge=0,
        le=10,
        alias="WORKER_TEST_RERUNS",
        description=(
            "F-11: rerun failing pytest tests up to N times in the sandbox and "
            "classify them stable_fail or flaky. Default 0 = off (no rerun, "
            "output identical to before). Sandbox mode only. Worst case wall "
            "time per command is (1 + N) * WORKER_TEST_TIMEOUT_SECONDS."
        ),
    )
    flaky_policy: str = Field(
        default="exclude",
        pattern="^(exclude|fail)$",
        alias="WORKER_FLAKY_POLICY",
        description=(
            "exclude (default): flaky tests are neither pass nor fail and block "
            "a 'verified' verdict. fail: flaky tests count as failures."
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
