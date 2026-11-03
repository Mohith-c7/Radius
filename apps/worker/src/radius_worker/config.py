"""Worker runtime configuration."""

from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator
from radius_repository.domain.clone_url import parse_allowed_hosts
from radius_shared.database.session import DatabaseSettings
from radius_shared.verdict_v2_flag import VerdictV2Mode, parse_verdict_v2_mode

MIN_POLL_INTERVAL_SECONDS = 30.0


class WorkerSettings(DatabaseSettings):
    """Runtime settings loaded from environment variables."""

    service_name: str = "radius-worker"
    repository_cache_dir: Path = Field(
        default=Path(".radius/repositories"),
        alias="REPOSITORY_CACHE_DIR",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.05,
        le=3600.0,
        alias="WORKER_POLL_INTERVAL_SECONDS",
    )
    job_stale_after_seconds: int = Field(
        default=1800,
        ge=60,
        le=604800,
        alias="WORKER_JOB_STALE_AFTER_SECONDS",
        description=(
            "A running job whose lease was not renewed for this long is treated as "
            "abandoned and returned to pending (or failed when its attempts are "
            "exhausted). A live worker renews the lease every "
            "WORKER_HEARTBEAT_INTERVAL_SECONDS, so this bounds crash recovery, not job length."
        ),
    )
    job_heartbeat_interval_seconds: float | None = Field(
        default=None,
        ge=1.0,
        le=3600.0,
        alias="WORKER_HEARTBEAT_INTERVAL_SECONDS",
        description=(
            "How often a worker renews the lease of the job it is running. Default "
            "(unset): the smaller of 60 and one third of WORKER_JOB_STALE_AFTER_SECONDS. "
            "When set it must be at most half of WORKER_JOB_STALE_AFTER_SECONDS."
        ),
    )
    job_retry_base_seconds: float = Field(
        default=15.0,
        ge=0.0,
        le=3600.0,
        alias="WORKER_JOB_RETRY_BASE_SECONDS",
        description=(
            "Retry backoff: a failed attempt is retried after base * 2^(attempt-1) "
            "seconds (+-25% jitter), capped by WORKER_JOB_RETRY_MAX_SECONDS. 0 = retry at once."
        ),
    )
    job_retry_max_seconds: float = Field(
        default=900.0,
        ge=1.0,
        le=86400.0,
        alias="WORKER_JOB_RETRY_MAX_SECONDS",
        description="Upper bound of the retry backoff delay.",
    )
    health_file: str = Field(
        default="",
        alias="WORKER_HEALTH_FILE",
        description=(
            "When set, the worker touches this file on every loop iteration and "
            "while a job's lease is renewed. The container healthcheck "
            "(python -m radius_worker.healthcheck) fails when it is older than "
            "WORKER_HEALTH_MAX_AGE_SECONDS."
        ),
    )
    health_max_age_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        alias="WORKER_HEALTH_MAX_AGE_SECONDS",
        description="Maximum age of WORKER_HEALTH_FILE before the worker is reported unhealthy.",
    )
    job_max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        alias="WORKER_JOB_MAX_ATTEMPTS",
    )
    analysis_deadline_seconds: int = Field(
        default=7200,
        ge=300,
        le=2592000,
        alias="WORKER_ANALYSIS_DEADLINE_SECONDS",
        description=(
            "An analysis that is still pending/running this long after its job last changed "
            "(queued, claimed or requeued) is failed by the reaper and its GitHub check "
            "completed. A job whose worker keeps renewing its lease (heartbeat) is never "
            "reaped for being long; one that stops heartbeating is recovered after "
            "WORKER_JOB_STALE_AFTER_SECONDS. Keep it above "
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
    mutation_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_MUTATION",
        description=(
            "Verdict v2 mutation evidence (default OFF; zero cost when off). Measures how "
            "well the linked tests detect small seeded faults in the changed Python "
            "symbols and uses the measured detection power instead of the static "
            "assertion cap. Mutants are generated code from the pull request: they run "
            "ONLY in the hardened sandbox, so this needs WORKER_TEST_EXECUTION_MODE=sandbox "
            "(otherwise the analysis records 'mutation unmeasured' and keeps the static "
            "cap). Needs RADIUS_FEATURE_VERDICT_V2 shadow or on."
        ),
    )
    mutation_max_mutants: int = Field(
        default=50,
        ge=5,
        le=500,
        alias="RADIUS_MUTATION_MAX_MUTANTS",
        description=(
            "Mutation evidence: hard cap on mutants run per analysis (seeded, stratified "
            "sample when more exist). Each mutant costs about one sandbox container run."
        ),
    )
    mutation_wall_clock_seconds: float = Field(
        default=600.0,
        ge=30.0,
        le=3600.0,
        alias="RADIUS_MUTATION_WALL_CLOCK_SECONDS",
        description=(
            "Mutation evidence: wall-clock budget for the whole mutation stage of one "
            "analysis. The stage runs inside the analysis job, so this is added latency. "
            "When it is too small for the sampled mutants the stage degrades (fewer "
            "mutants, finally 'unmeasured, static cap')."
        ),
    )
    mutation_mutant_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        alias="RADIUS_MUTATION_MUTANT_TIMEOUT_SECONDS",
        description=(
            "Mutation evidence: upper bound of the per-mutant sandbox timeout (the "
            "effective timeout is 3x the median baseline run, clamped to 5-120 s and to "
            "this value). A timed-out mutant is excluded from the detection score."
        ),
    )
    mutation_stage2_enabled: bool = Field(
        default=False,
        alias="RADIUS_MUTATION_STAGE2",
        description=(
            "Mutation evidence stage 2 (default OFF; only used when RADIUS_FEATURE_MUTATION "
            "is on). Each mutant that survives the linked tests is also run, in the same "
            "hardened sandbox and with early exit, against the repository's other tests "
            "that import the mutated module. A mutant killed only by such an unlinked test "
            "is reported as a link gap (the criterion's links are incomplete) instead of "
            "counting as weak evidence. Unlinked tests never add support."
        ),
    )
    mutation_stage2_max_tests: int = Field(
        default=60,
        ge=1,
        le=500,
        alias="RADIUS_MUTATION_STAGE2_MAX_TESTS",
        description=(
            "Mutation stage 2: maximum wider tests run against one surviving mutant "
            "(deterministic order: sorted test ids). Tests beyond the cap are not tried."
        ),
    )
    mutation_stage2_wall_clock_seconds: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        alias="RADIUS_MUTATION_STAGE2_WALL_CLOCK_SECONDS",
        description=(
            "Mutation stage 2: wall-clock budget for the whole stage (separate from the "
            "stage 1 budget; added latency). Survivors not reached keep their stage 1 "
            "result and are counted as skipped_for_budget."
        ),
    )
    tamper_rules_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_TAMPER_RULES",
        description=(
            "EV-02: run the deterministic tamper rules (weakened or disabled tests, "
            "CI/config weakening, hallucinated dependencies) on the diff and log finding "
            "counts. Nothing is persisted yet (EV-01/LK-05); failures never affect the "
            "analysis."
        ),
    )
    assertion_extraction_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_ASSERTION_EXTRACTION",
        description=(
            "LK-04: statically extract the assertions of the repository's test files "
            "(AST only, nothing is executed) and log their counts. Nothing is "
            "persisted yet (LK-05); failures never affect the analysis."
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
    github_app_private_key_path: str = Field(
        default="",
        alias="GITHUB_APP_PRIVATE_KEY_PATH",
        description=(
            "Path to the GitHub App private key (.pem). Used when "
            "`GITHUB_APP_PRIVATE_KEY` is empty, so the key never has to be pasted "
            "into an environment variable or committed."
        ),
    )
    github_installation_id: int | None = Field(
        default=None,
        alias="GITHUB_INSTALLATION_ID",
    )

    @property
    def heartbeat_interval(self) -> float:
        """Seconds between lease renewals (explicit setting or the derived default)."""

        if self.job_heartbeat_interval_seconds is not None:
            return self.job_heartbeat_interval_seconds
        return min(60.0, self.job_stale_after_seconds / 3)

    def dashboard_analysis_url(self, analysis_id: object) -> str | None:
        """Link to an analysis in the dashboard, from ``DASHBOARD_BASE_URL``.

        ``None`` when the base URL is unset or not an http(s) URL, so the Check Run and PR
        comment then carry no link instead of a broken one.
        """

        base = (self.dashboard_base_url or "").strip().rstrip("/")
        if not base.lower().startswith(("http://", "https://")):
            return None
        return f"{base}/analyses/{analysis_id}"
    github_poll_interval_seconds: float = Field(
        default=0.0,
        alias="RADIUS_GITHUB_POLL_INTERVAL_SECONDS",
        description=(
            "Opt-in pull-based trigger (no webhook needed): every this many seconds "
            "(plus or minus 10 percent jitter) the worker lists the open, non-draft "
            "pull requests of connected repositories whose GitHub App installation it "
            "can reach and queues an analysis for every head commit that has none yet. "
            "0 (default) = off. Values from 1 to 29 are raised to 30; negative = off. "
            "Needs GITHUB_APP_ID and a private key in the worker."
        ),
    )
    github_poll_max_analyses_per_tick: int = Field(
        default=10,
        ge=1,
        le=200,
        alias="RADIUS_GITHUB_POLL_MAX_ANALYSES_PER_TICK",
        description=(
            "Upper bound of analyses one poll tick may queue; the rest wait for the "
            "next tick."
        ),
    )
    github_poll_max_repositories_per_tick: int = Field(
        default=25,
        ge=1,
        le=500,
        alias="RADIUS_GITHUB_POLL_MAX_REPOSITORIES_PER_TICK",
        description=(
            "Upper bound of repositories one poll tick lists from GitHub (one API call "
            "each); repositories take turns so none starves."
        ),
    )

    git_clone_timeout_seconds: float = Field(
        default=300.0,
        ge=5.0,
        le=3600.0,
        alias="RADIUS_GIT_CLONE_TIMEOUT_SECONDS",
        description=(
            "Time limit for `git clone`. The git process group is killed on expiry and the "
            "job is retried."
        ),
    )
    git_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=1800.0,
        alias="RADIUS_GIT_TIMEOUT_SECONDS",
        description=(
            "Time limit for every other git command (fetch, worktree, checkout, gc). The "
            "process group is killed on expiry and the job is retried."
        ),
    )
    git_lock_timeout_seconds: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
        alias="RADIUS_GIT_LOCK_TIMEOUT_SECONDS",
        description=(
            "How long a job waits for the exclusive lock of one repository cache (held "
            "while fetching or creating a worktree) before it fails retryably."
        ),
    )
    git_stale_lock_seconds: float = Field(
        default=900.0,
        ge=30.0,
        le=86400.0,
        alias="RADIUS_GIT_STALE_LOCK_SECONDS",
        description=(
            "A git `index.lock` older than this, found while the worker holds the repository "
            "lock, is a leftover of a dead process and is removed."
        ),
    )
    git_cache_max_idle_days: int = Field(
        default=0,
        ge=0,
        le=3650,
        alias="RADIUS_GIT_CACHE_MAX_IDLE_DAYS",
        description=(
            "Opt-in pruning of repository caches: every hour a cache unused for this many "
            "days (and not locked or in use by a worktree) is deleted and re-cloned on next "
            "use. 0 (default) = fall back to RADIUS_RETENTION_DAYS when that is set, else "
            "never prune. Cache housekeeping (stale locks, `git worktree prune`, "
            "`git gc --auto`, orphaned analysis worktrees) always runs."
        ),
    )

    github_poll_failed_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        alias="RADIUS_GITHUB_POLL_FAILED_RETRIES",
        description=(
            "How many times the poller queues a head commit again after its analysis "
            "FAILED (for example after a GitHub or network outage that outlasted the job "
            "retries). Spacing doubles from RADIUS_GITHUB_POLL_FAILED_RETRY_DELAY_SECONDS. "
            "0 = never retry a failed head automatically (re-run it explicitly)."
        ),
    )
    github_poll_failed_retry_delay_seconds: float = Field(
        default=900.0,
        ge=60.0,
        le=86400.0,
        alias="RADIUS_GITHUB_POLL_FAILED_RETRY_DELAY_SECONDS",
        description="Minimum wait after a failed analysis before the poller retries its head.",
    )

    retention_days: int = Field(
        default=0,
        alias="RADIUS_RETENTION_DAYS",
        description=(
            "Opt-in data retention: every hour the worker deletes rows older than this many "
            "days from idempotency_keys, exhausted verdict_v2_requests outbox rows and "
            "mutation_result_cache. Never touches analyses, verdicts, evidence or audit "
            "rows. 0 (default) = off; values from 1 to 6 are raised to 7."
        ),
    )
    retention_dry_run: bool = Field(
        default=False,
        alias="RADIUS_RETENTION_DRY_RUN",
        description=(
            "With RADIUS_RETENTION_DAYS set: only log how many rows each retention pass "
            "would delete, delete nothing."
        ),
    )

    @field_validator("retention_days", mode="before")
    @classmethod
    def _normalise_retention_days(cls, value: object) -> int:
        from radius_worker.maintenance import normalise_retention_days

        return normalise_retention_days(value)

    @field_validator("github_poll_interval_seconds", mode="after")
    @classmethod
    def _clamp_poll_interval(cls, value: float) -> float:
        if value <= 0:
            return 0.0
        return max(value, MIN_POLL_INTERVAL_SECONDS)

    @model_validator(mode="after")
    def _check_job_timing(self) -> Self:
        if (
            self.job_heartbeat_interval_seconds is not None
            and self.job_heartbeat_interval_seconds * 2 > self.job_stale_after_seconds
        ):
            msg = (
                "WORKER_HEARTBEAT_INTERVAL_SECONDS must be at most half of "
                "WORKER_JOB_STALE_AFTER_SECONDS, otherwise a healthy job is recovered "
                "as stale."
            )
            raise ValueError(msg)
        if self.analysis_deadline_seconds <= self.job_stale_after_seconds:
            msg = (
                "WORKER_ANALYSIS_DEADLINE_SECONDS must be larger than "
                "WORKER_JOB_STALE_AFTER_SECONDS."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _load_private_key_file(self) -> Self:
        if not self.github_app_private_key and self.github_app_private_key_path:
            from radius_github.client import read_private_key_file

            self.github_app_private_key = read_private_key_file(
                self.github_app_private_key_path
            )
        return self

    @field_validator("github_installation_id", mode="before")
    @classmethod
    def _parse_installation_id(cls, v):
        if v is None or v == "" or v == 0 or v == "0":
            return None
        return int(v)

    git_allowed_hosts: str = Field(
        default="github.com",
        alias="RADIUS_GIT_ALLOWED_HOSTS",
        description=(
            "Comma separated hosts the worker may clone from (https only). Default "
            "`github.com`; set your GitHub Enterprise Server host to use it instead. "
            "A stored clone URL on any other host is refused, and the installation "
            "token is never sent to a host that is not listed."
        ),
    )

    @field_validator("git_allowed_hosts")
    @classmethod
    def _valid_git_hosts(cls, value: str) -> str:
        parse_allowed_hosts(value)
        return value

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

    verdict_v2_check_conclusions: str = Field(
        default="advisory",
        alias="RADIUS_VERDICT_V2_CHECK_CONCLUSIONS",
        description=(
            "Check Run conclusion mapping for Verdict v2 (alpha). advisory (default): "
            "never success; verified, insufficient_evidence and needs_review are neutral, "
            "failed is failure only when decided by R1a/R1b/R1c (failing linked test, "
            "failing CI, high-severity tamper). strict: verified is success."
        ),
    )
    verdict_v2_confirm_policy: str = Field(
        default="allow_unverified",
        alias="RADIUS_VERDICT_V2_CONFIRM_POLICY",
        description=(
            "Who may lift the unconfirmed-intent block and the author-hint cap by confirming "
            "a criterion (B-07). The confirmer is the authenticated principal recorded by the "
            "API. A confirmer linked to the PR author's GitHub login never counts. "
            "allow_unverified (default): a confirmer whose GitHub link is unknown counts but "
            "is labelled 'unverified confirmer' in the verdict. require_second_person: only "
            "a confirmer verifiably linked to a different GitHub account counts. An "
            "unrecognised value stops the worker at start."
        ),
    )
    intent_extraction_mode: str = Field(
        default="sections",
        alias="RADIUS_INTENT_EXTRACTION_MODE",
        description=(
            "Deterministic intent extraction mode (worker, Stage A input). sections "
            "(default): acceptance-style sections, checklists, Gherkin and spec files only. "
            "summary (opt-in): additionally proposes low-weight criteria from a "
            "conventional-commit PR title and behavioural bullets under Summary/Changes/"
            "What/Why/Description headings; never confirmed, provenance author_pr_body. "
            "llm (opt-in, DEC-034): summary plus guarded LLM proposals from the PR title and "
            "body ONLY (the PR text is sent to a third-party model provider); needs "
            "RADIUS_LLM_INTENT_ENABLED, RADIUS_LLM_INTENT_ORGS and ANTHROPIC_API_KEY, "
            "otherwise it logs why and behaves as summary; proposals are llm_proposed, never "
            "confirmed, and block verified until a human confirms them. "
            "Unknown values mean sections."
        ),
    )

    suggest_tests_enabled: bool = Field(
        default=False,
        alias="RADIUS_FEATURE_SUGGEST_TESTS",
        description=(
            "Verdict v2 (DEC-034, opt-in, default off): for criteria that are unevidenced or "
            "weak, ask an LLM for one pytest snippet and show it, after a deterministic gate "
            "(parses, imports only the changed symbols, has an assertion rated strong), in a "
            "separate 'Suggested tests (not run, not evidence)' block. Never executed, never "
            "evidence, never changes the verdict. Criterion text and changed symbol NAMES "
            "(no source code) are sent to a third-party model provider; needs "
            "RADIUS_LLM_INTENT_ENABLED, RADIUS_LLM_INTENT_ORGS and ANTHROPIC_API_KEY, "
            "otherwise nothing is sent."
        ),
    )

    @field_validator("verdict_v2_check_conclusions", mode="before")
    @classmethod
    def _parse_check_conclusions(cls, value: object) -> str:
        """Only the exact word ``strict`` opts in; anything else stays advisory."""
        return "strict" if str(value).strip().lower() == "strict" else "advisory"

    @field_validator("verdict_v2_confirm_policy", mode="before")
    @classmethod
    def _check_confirm_policy(cls, value: object) -> str:
        text = str(value).strip().lower() or "allow_unverified"
        if text == "allow":
            text = "allow_unverified"
        if text not in {"allow_unverified", "require_second_person"}:
            msg = "RADIUS_VERDICT_V2_CONFIRM_POLICY must be allow_unverified or require_second_person."
            raise ValueError(msg)
        return text

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
