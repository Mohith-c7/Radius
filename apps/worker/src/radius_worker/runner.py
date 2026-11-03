"""Worker runtime shell."""

import base64
import signal
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
    SubprocessGitDiffProvider,
    UnifiedDiffChangeAnalyzer,
)
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import CURRENT_SCORE_KIND
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
    SqlAlchemyConfidenceStore,
)
from radius_github import GitHubAnalysisPublisher, GitHubAppClient, GitHubAppSettings
from radius_github.intent_rest import EtagCache, HttpTransport
from radius_github.publisher import CommentPublishError, GitHubAnalysisReport
from radius_graph.application import GraphApplicationService
from radius_graph.infrastructure import InMemoryGraphStore, SqlAlchemyGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_repository.infrastructure import LocalGitRepositoryClient
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.database.session import (
    create_database_engine,
    create_session_factory,
)
from radius_shared.errors import NotFoundError, ValidationError
from radius_shared.logging import configure_logging, get_logger
from radius_shared.observability import (
    ObservabilitySettings,
    bind_correlation,
    configure_tracing,
    continue_trace,
    span,
    stage,
)
from radius_shared.observability import metrics as obs_metrics
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    SqlAlchemyTestStore,
    StaticTestCommandPlanner,
    SubprocessTestRunner,
)
from sqlalchemy.orm import Session, sessionmaker

from radius_worker.config import WorkerSettings
from radius_worker.execution_mode import (
    TestExecutionMode,
    build_test_runner,
    require_sandbox_ready,
    resolve_test_execution_mode,
)
from radius_worker.intent_ingestion import ingest_intent_best_effort
from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)
from radius_worker.poller import PullRequestPoller
from radius_worker.queue import InMemoryAnalysisQueue
from radius_worker.verdict_v2.publish import publish_in_job as publish_v2_in_job
from radius_worker.verdict_v2.publish import v2_replaces_v1
from radius_worker.verdict_v2.requests import Recomputer as VerdictV2Recomputer
from radius_worker.verdict_v2.requests import (
    process_pending as process_verdict_v2_requests,
)

LOGGER = get_logger(__name__)


class AnalysisStuckError(RuntimeError):
    """An analysis was stopped by the reaper because it could not finish."""


def run_worker() -> None:
    """Start the SQL-backed worker process."""

    settings = WorkerSettings()
    configure_logging(settings.log_level)
    configure_observability()
    runtime = create_sql_worker_runtime(settings)
    if obs_metrics.metrics_enabled():
        obs_metrics.set_queue_depth_provider(runtime.queue_depths)
    _install_stop_handlers(runtime.stop_event)
    print("Radius worker ready")
    runtime.run_loop(poll_interval_seconds=settings.poll_interval_seconds)
    LOGGER.info("Radius worker stopped", extra={"outcome": "worker_stopped"})


def _install_stop_handlers(stop_event: threading.Event) -> None:
    """SIGTERM / SIGINT finish the current job, then end the loop (no new work is claimed)."""

    def _stop(signum, _frame) -> None:
        LOGGER.info("Stop requested", extra={"outcome": "worker_stopping", "signal": signum})
        stop_event.set()

    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, _stop)


def configure_observability(settings: ObservabilitySettings | None = None) -> None:
    """Enable optional tracing/metrics from env settings (default: off)."""

    settings = settings or ObservabilitySettings()
    if settings.service_name == "radius":
        settings = settings.model_copy(update={"service_name": "radius-worker"})
    configure_tracing(settings)
    if obs_metrics.configure_metrics(settings.metrics_enabled):
        obs_metrics.start_metrics_server(settings.worker_metrics_port)


@dataclass(slots=True)
class SqlAlchemyWorkerRuntime:
    """SQL-backed worker runtime with explicit transaction boundaries."""

    session_factory: sessionmaker[Session]
    repository_cache_dir: Path
    git_client: LocalGitRepositoryClient
    settings: WorkerSettings
    github_client: GitHubAppClient
    #: IN-02: HTTP transport for intent ingestion (``None`` = real urllib). Tests inject a fake.
    intent_transport: HttpTransport | None = None
    #: IN-02: conditional-request cache; process-local and bounded.
    intent_etag_cache: EtagCache = field(default_factory=EtagCache)
    #: VS-07: Stage B recompute used by the verdict v2 outbox consumer (``None`` =
    #: republish the latest stored verdict without recomputing). Wired by VS-06.
    verdict_v2_recomputer: VerdictV2Recomputer | None = None
    #: Set to end ``run_loop`` after the current job (SIGTERM / SIGINT in ``run_worker``).
    stop_event: threading.Event = field(default_factory=threading.Event)
    #: Opt-in pull request poller (``None`` = off; built from settings when unset).
    poller: PullRequestPoller | None = None

    def __post_init__(self) -> None:
        if self.poller is None and self.settings.github_poll_interval_seconds > 0:
            if not self.github_client.settings.enabled:
                LOGGER.warning(
                    "RADIUS_GITHUB_POLL_INTERVAL_SECONDS is set but GITHUB_APP_ID / the "
                    "private key are missing in the worker; the poller stays off",
                    extra={"outcome": "poll_disabled"},
                )
                return
            self.poller = PullRequestPoller(
                session_factory=self.session_factory,
                github_client=self.github_client,
                settings=self.settings,
                should_stop=self.stop_event.is_set,
            )

    def run_once(self) -> bool:
        """Claim and execute one durable analysis job."""

        job = self._claim_job()
        if job is None:
            return False
        organization_id = self._organization_id(job.analysis_id)
        # Persisted at enqueue; kept across retries so attempts share one trace.
        traceparent = job.traceparent
        started = time.perf_counter()
        outcome = "completed"
        with (
            bind_correlation(
                analysis_id=job.analysis_id,
                job_id=job.id,
                organization_id=organization_id,
            ),
            continue_trace(traceparent),
            span("worker.job", **{"radius.attempt": job.attempts}),
        ):
            try:
                self._run_claimed_job(job)
            except Exception:
                outcome = "failed"
                raise
            finally:
                obs_metrics.observe_job(time.perf_counter() - started, outcome)
        return True

    def queue_depths(self) -> dict[str, int]:
        """Jobs per status, for the queue-depth gauge."""

        with self.session_factory() as session:
            return self._queue(session).depth_by_status()

    def _organization_id(self, analysis_id):
        """Best-effort org id for log correlation; never fails the job."""

        try:
            with self.session_factory() as session:
                analysis = session.get(db_models.Analysis, analysis_id)
                repository = (
                    session.get(db_models.Repository, analysis.repository_id)
                    if analysis is not None
                    else None
                )
                return repository.organization_id if repository else None
        except Exception:
            return None

    def _run_claimed_job(self, job) -> None:
        """Execute one claimed job inside its correlation/trace context."""

        try:
            with self.session_factory() as session:
                skip_reason = _skip_reason(session, job.analysis_id)
                if skip_reason is not None:
                    # Cancelled (e.g. PR closed) between enqueue and claim: do
                    # not clone, run or publish anything for it.
                    self._queue(session).skip_claimed(job.analysis_id, skip_reason)
                    session.commit()
                    LOGGER.info(
                        "Analysis job skipped",
                        extra={
                            "analysis_id": str(job.analysis_id),
                            "job_id": str(job.id),
                            "outcome": "cancelled",
                            "reason": skip_reason,
                        },
                    )
                    return
                # Best-effort: shows "in progress" on the PR while we work. It
                # never raises, so it cannot fail the analysis.
                _publish_github_in_progress(
                    session=session,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                )
                # Best-effort (IN-02): intent sources -> snapshot. Own session and
                # transaction; never raises, so it cannot fail the analysis.
                ingest_intent_best_effort(
                    session_factory=self.session_factory,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                    installation_id_for=lambda s: _github_installation_id(
                        session=s,
                        analysis_id=job.analysis_id,
                        settings=self.settings,
                    ),
                    transport=self.intent_transport,
                    etag_cache=self.intent_etag_cache,
                )
                orchestrator = _create_sql_orchestrator(session, self.settings)
                clone_headers = _github_clone_headers(
                    session=session,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                )
                command = load_persisted_analysis_command(
                    session=session,
                    analysis_id=job.analysis_id,
                    repository_cache_dir=self.repository_cache_dir,
                    git_client=self.git_client,
                    extra_headers=clone_headers,
                )
                orchestrator.execute(command)
                if self.settings.verdict_v2_mode != "off":
                    # Verdict v2 Stage A/B (VS-05, flag RADIUS_FEATURE_VERDICT_V2):
                    # best-effort, own sessions, never raises; v1 is unaffected.
                    from radius_worker.verdict_v2.scoring import (
                        run_verdict_v2_for_analysis,
                    )

                    run_verdict_v2_for_analysis(
                        session_factory=self.session_factory,
                        analysis_id=job.analysis_id,
                        command=command,
                        settings=self.settings,
                    )
                _publish_github_result(
                    session=session,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                )
                self._queue(session).complete(job.analysis_id)
                session.commit()
        except Exception as exc:
            self._record_job_failure(job, exc)
            raise
        LOGGER.info(
            "Analysis job finished",
            extra={
                "analysis_id": str(job.analysis_id),
                "job_id": str(job.id),
                "attempt": job.attempts,
                "outcome": "completed",
            },
        )

    def _record_job_failure(self, job, exc: Exception) -> None:
        """Persist a failed attempt; on the final attempt fail the analysis too.

        The pipeline session was rolled back, so the orchestrator's own
        ``fail_analysis`` did not persist, and failures before the
        orchestrator ran (token, clone, checkout) never touched the analysis.
        The terminal state is therefore written here, in a fresh session,
        and committed before the GitHub check is completed.
        """

        error = redact_secrets(f"{exc.__class__.__name__}: {exc}", max_length=2000)
        final_attempt = job.attempts >= self.settings.job_max_attempts
        LOGGER.error(
            "Analysis job attempt failed",
            extra={
                "analysis_id": str(job.analysis_id),
                "job_id": str(job.id),
                "attempt": job.attempts,
                "outcome": "failed" if final_attempt else "requeued",
                "error": error,
                "traceback": redact_secrets(
                    "".join(traceback.format_exception(exc)), max_length=8000
                ),
            },
        )
        with self.session_factory() as session:
            queue = self._queue(session)
            if final_attempt:
                queue.fail(job.analysis_id, error)
                queue.mark_analysis_failed(job.analysis_id)
            else:
                queue.requeue(job.analysis_id, error)
                obs_metrics.record_retry()
            session.commit()
            if final_attempt:
                _publish_github_failure(
                    session=session,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                    error=exc,
                )

    def reap_stuck_analyses(self) -> list:
        """Fail analyses that can no longer finish and complete their checks.

        Covers jobs whose attempts were exhausted by stale-claim recovery (a
        worker died mid-run) and analyses past ``analysis_deadline_seconds``.
        """

        with self.session_factory() as session:
            reaped = self._queue(session).reap_stuck_analyses(
                deadline=timedelta(seconds=self.settings.analysis_deadline_seconds),
            )
            session.commit()
            for item in reaped:
                _publish_github_failure(
                    session=session,
                    analysis_id=item.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                    error=AnalysisStuckError(item.reason),
                )
        return reaped

    def run_loop(
        self,
        *,
        poll_interval_seconds: float = 2.0,
        stop_after_idle_cycles: int | None = None,
    ) -> None:
        """Run the SQL-backed polling loop.

        A failing job never stops the loop: the failure is already recorded
        (requeued or failed) by ``run_once``, so the loop logs and moves on.
        The reaper runs every ``reaper_interval_seconds``.
        """

        idle_cycles = 0
        next_reap = 0.0
        next_poll = (
            time.monotonic() + self.poller.first_delay() if self.poller is not None else None
        )
        if self.poller is not None:
            LOGGER.info(
                "GitHub pull request poller enabled",
                extra={
                    "outcome": "poll_enabled",
                    "interval_seconds": self.poller.interval,
                    "max_analyses_per_tick": self.settings.github_poll_max_analyses_per_tick,
                    "max_repositories_per_tick": (
                        self.settings.github_poll_max_repositories_per_tick
                    ),
                },
            )
        while not self.stop_event.is_set():
            self._process_verdict_v2_requests()
            if (
                self.poller is not None
                and next_poll is not None
                and time.monotonic() >= next_poll
            ):
                self.poller.poll_once()  # never raises
                next_poll = time.monotonic() + self.poller.next_delay()
            if time.monotonic() >= next_reap:
                next_reap = time.monotonic() + self.settings.reaper_interval_seconds
                try:
                    self.reap_stuck_analyses()
                except Exception as exc:
                    LOGGER.error(
                        "Stuck-analysis reaper failed",
                        extra={"outcome": "reaper_error", "error": redact_secrets(exc)},
                    )
            try:
                processed = self.run_once()
            except Exception as exc:
                LOGGER.warning(
                    "Worker iteration failed; continuing",
                    extra={"outcome": "iteration_error", "error": redact_secrets(exc)},
                )
                idle_cycles = 0
                self.stop_event.wait(poll_interval_seconds)
                continue
            if processed:
                idle_cycles = 0
                continue
            idle_cycles += 1
            if (
                stop_after_idle_cycles is not None
                and idle_cycles >= stop_after_idle_cycles
            ):
                return
            self.stop_event.wait(poll_interval_seconds)

    def _process_verdict_v2_requests(self) -> None:
        """VS-07: republish after CI. No-op with the flag off; never raises."""

        if self.settings.verdict_v2_mode == VerdictV2Mode.OFF:
            return
        try:
            process_verdict_v2_requests(
                session_factory=self.session_factory,
                settings=self.settings,
                github_client=self.github_client,
                recomputer=self.verdict_v2_recomputer,
            )
        except Exception as exc:
            LOGGER.warning(
                "Verdict v2 outbox pass failed; continuing",
                extra={"outcome": "verdict_v2_outbox_error", "error": redact_secrets(exc)},
            )

    def _claim_job(self):
        with self.session_factory() as session:
            queue = self._queue(session)
            job = queue.claim_next()
            session.commit()
            return job

    def _queue(self, session: Session) -> SqlAlchemyAnalysisJobQueue:
        return SqlAlchemyAnalysisJobQueue(
            session,
            stale_after=timedelta(seconds=self.settings.job_stale_after_seconds),
            max_attempts=self.settings.job_max_attempts,
        )


def create_sql_worker_runtime(settings: WorkerSettings) -> SqlAlchemyWorkerRuntime:
    """Create the SQL-backed worker runtime."""

    # Fail fast at startup on a forbidden execution mode (e.g. unsafe in prod).
    require_sandbox_ready(resolve_test_execution_mode(settings), settings)
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    verdict_v2_recomputer = None
    if settings.verdict_v2_mode != VerdictV2Mode.OFF:
        from radius_worker.verdict_v2.scoring import create_recomputer

        verdict_v2_recomputer = create_recomputer(
            session_factory, settings.verdict_v2_mode, settings
        )
    return SqlAlchemyWorkerRuntime(
        session_factory=session_factory,
        repository_cache_dir=settings.repository_cache_dir,
        git_client=LocalGitRepositoryClient(),
        settings=settings,
        github_client=GitHubAppClient(_github_settings(settings)),
        verdict_v2_recomputer=verdict_v2_recomputer,
    )


def run_worker_once(
    *,
    queue,
    orchestrator: Phase1AnalysisOrchestrator,
    command_loader: Callable[[object], ExecuteAnalysisCommand],
) -> bool:
    """Claim, execute, and acknowledge one analysis job."""

    job = queue.claim_next()
    if job is None:
        return False
    analysis_id = job.analysis_id if hasattr(job, "analysis_id") else job
    try:
        orchestrator.execute(command_loader(job))
    except Exception as exc:
        if hasattr(queue, "fail"):
            queue.fail(analysis_id, str(exc))
        raise
    if hasattr(queue, "complete"):
        queue.complete(analysis_id)
    return True


def run_worker_loop(
    *,
    queue,
    orchestrator: Phase1AnalysisOrchestrator,
    command_loader: Callable[[object], ExecuteAnalysisCommand],
    poll_interval_seconds: float = 2.0,
    stop_after_idle_cycles: int | None = None,
) -> None:
    """Run a polling worker loop with optional bounded idle cycles for tests."""

    idle_cycles = 0
    while True:
        processed = run_worker_once(
            queue=queue,
            orchestrator=orchestrator,
            command_loader=command_loader,
        )
        if processed:
            idle_cycles = 0
            continue
        idle_cycles += 1
        if stop_after_idle_cycles is not None and idle_cycles >= stop_after_idle_cycles:
            return
        time.sleep(poll_interval_seconds)


def create_local_orchestrator(
    queue: InMemoryAnalysisQueue | None = None,
) -> Phase1AnalysisOrchestrator:
    """Create an in-memory worker orchestrator for local development/tests."""

    graph_store = InMemoryGraphStore()
    analysis_service = AnalysisApplicationService(
        InMemoryAnalysisStore(),
        pipeline=queue,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    return Phase1AnalysisOrchestrator(
        analysis_service=analysis_service,
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(),
            default_language_parser_registry(),
        ),
        graph_service=GraphApplicationService(graph_store),
        graph_store=graph_store,
        testing_service=TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=InMemoryTestStore(),
            planner=StaticTestCommandPlanner(),
            runner=SubprocessTestRunner(),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=InMemoryConfidenceStore(),
        ),
    )


def load_persisted_analysis_command(
    *,
    session: Session,
    analysis_id,
    repository_cache_dir: Path,
    git_client: LocalGitRepositoryClient,
    extra_headers: tuple[str, ...] = (),
) -> ExecuteAnalysisCommand:
    """Resolve an analysis row into an executable worker command."""

    analysis = session.get(db_models.Analysis, analysis_id)
    if analysis is None:
        msg = f"Analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    repository = session.get(db_models.Repository, analysis.repository_id)
    if repository is None:
        msg = f"Repository {analysis.repository_id} was not found."
        raise NotFoundError(msg)
    pull_request = session.get(db_models.PullRequest, analysis.pull_request_id)
    if pull_request is None:
        msg = f"Pull request {analysis.pull_request_id} was not found."
        raise NotFoundError(msg)

    destination = _repository_cache_path(repository_cache_dir, repository)
    repository_path = git_client.clone_or_fetch(
        repository.clone_url,
        destination,
        extra_headers=extra_headers,
    )
    if hasattr(git_client, "fetch_pull_request") and pull_request.github_pr_number:
        try:
            git_client.fetch_pull_request(
                repository_path,
                pull_request.github_pr_number,
                extra_headers=extra_headers,
            )
        except Exception:
            LOGGER.debug(
                "Could not fetch pull request ref directly; continuing with commit SHA checkout.",
                extra={"pr_number": pull_request.github_pr_number},
            )
    git_client.checkout(repository_path, analysis.commit_sha)
    return ExecuteAnalysisCommand(
        analysis_id=analysis.id,
        repository_id=repository.id,
        repository_path=repository_path,
        base_ref=f"origin/{pull_request.target_branch}",
        head_ref=analysis.commit_sha,
    )


def _create_sql_orchestrator(
    session: Session,
    settings: WorkerSettings | None = None,
) -> Phase1AnalysisOrchestrator:
    graph_store = SqlAlchemyGraphStore(session)
    # Runner selection is security-critical: see radius_worker.execution_mode.
    execution_mode = resolve_test_execution_mode(settings)
    return Phase1AnalysisOrchestrator(
        analysis_service=AnalysisApplicationService(
            SqlAlchemyAnalysisStore(session),
            change_analyzer=UnifiedDiffChangeAnalyzer(),
            diff_provider=SubprocessGitDiffProvider(),
        ),
        parser_service=ParserApplicationService(
            FilesystemSourceDiscovery(),
            default_language_parser_registry(),
        ),
        graph_service=GraphApplicationService(graph_store),
        graph_store=graph_store,
        testing_service=TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=SqlAlchemyTestStore(session),
            planner=StaticTestCommandPlanner(),
            runner=build_test_runner(execution_mode, settings),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=SqlAlchemyConfidenceStore(session),
        ),
        execute_tests=execution_mode != TestExecutionMode.DISABLED,
        symbol_impact_enabled=bool(settings and settings.symbol_impact_enabled),
        symbol_changes_enabled=bool(settings and settings.symbol_changes_enabled),
        tamper_rules_enabled=bool(settings and settings.tamper_rules_enabled),
        assertion_extraction_enabled=bool(settings and settings.assertion_extraction_enabled),
        flaky_policy=(settings.flaky_policy if settings else "exclude"),
    )


def _repository_cache_path(
    repository_cache_dir: Path,
    repository: db_models.Repository,
) -> Path:
    owner = _safe_path_segment(repository.owner)
    name = _safe_path_segment(repository.name)
    return repository_cache_dir / owner / f"{name}-{repository.github_repository_id}"


def _safe_path_segment(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value
    )


def _github_settings(settings: WorkerSettings) -> GitHubAppSettings:
    return GitHubAppSettings(
        RADIUS_ENV=settings.environment,
        RADIUS_LOG_LEVEL=settings.log_level,
        GITHUB_APP_ID=settings.github_app_id,
        GITHUB_APP_PRIVATE_KEY=settings.github_app_private_key,
        GITHUB_APP_PRIVATE_KEY_PATH=settings.github_app_private_key_path,
        GITHUB_INSTALLATION_ID=settings.github_installation_id,
        GITHUB_API_BASE_URL=settings.github_api_base_url,
        GITHUB_API_VERSION=settings.github_api_version,
        GITHUB_TIMEOUT_SECONDS=settings.github_timeout_seconds,
    )


def _github_clone_headers(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
) -> tuple[str, ...]:
    github_settings = _github_settings(settings)
    if not github_settings.enabled:
        return ()
    installation_id = _github_installation_id(
        session=session,
        analysis_id=analysis_id,
        settings=settings,
    )
    token = github_client.create_installation_token(installation_id).token
    return (_git_basic_auth_header(token),)


def _git_basic_auth_header(token: str) -> str:
    """Git-over-HTTPS auth for a GitHub App installation token.

    GitHub's smart-HTTP git endpoints take HTTP Basic auth with the username
    ``x-access-token`` and the installation token as the password (documented as
    ``git clone https://x-access-token:TOKEN@github.com/owner/repo.git``); a
    ``Bearer`` header is only valid for the REST API. The header is passed to
    git through the child process environment (see ``LocalGitRepositoryClient``),
    never on argv, in ``.git/config`` or in the remote URL.
    """

    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return f"Authorization: Basic {credentials}"


def _publish_github_result(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
) -> None:
    github_settings = _github_settings(settings)
    if not settings.github_publish_results or not github_settings.enabled:
        return
    # VS-08: with the flag ``on`` and a stored v2 verdict that is ok, v2 is
    # published instead of v1; any v2 problem falls through to v1 below.
    if v2_replaces_v1(session, settings, analysis_id) and publish_v2_in_job(
        session,
        analysis_id=analysis_id,
        settings=settings,
        github_client=github_client,
    ):
        return
    try:
        installation_id = _github_installation_id(
            session=session,
            analysis_id=analysis_id,
            settings=settings,
        )
        report = _github_report(session, analysis_id, settings)
        with stage("publish"):
            GitHubAnalysisPublisher(github_client).publish(
                installation_id=installation_id,
                report=report,
            )
        LOGGER.info(
            "Successfully published GitHub Check Run and PR comment",
            extra={"analysis_id": str(analysis_id), "pr_number": report.pull_request_number},
        )
    except CommentPublishError as exc:
        # The check run is already completed; only the PR comment failed.
        LOGGER.warning(
            "Could not publish GitHub PR comment: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(analysis_id), "outcome": "publish_error"},
        )
    except Exception as exc:
        LOGGER.warning(
            "Could not publish GitHub Check Run or PR comment: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(analysis_id), "outcome": "publish_error"},
        )
        # The in-progress run opened at job start must not stay stuck: complete
        # it as "not verified" rather than leaving it spinning forever.
        _publish_github_failure(
            session=session,
            analysis_id=analysis_id,
            settings=settings,
            github_client=github_client,
            error=RuntimeError("Radius could not publish its result to GitHub."),
        )


def _skip_reason(session: Session, analysis_id) -> str | None:
    """Why a freshly claimed job must not run, or ``None`` to run it."""

    analysis = session.get(db_models.Analysis, analysis_id)
    if analysis is not None and analysis.status == db_enums.AnalysisStatus.CANCELLED:
        return "Analysis was cancelled before it started."
    repository = (
        session.get(db_models.Repository, analysis.repository_id)
        if analysis is not None
        else None
    )
    if repository is None:
        return None
    if repository.status == db_enums.RepositoryStatus.DISCONNECTED:
        return "Repository is disconnected from Radius."
    organization = session.get(db_models.Organization, repository.organization_id)
    if (
        organization is not None
        and organization.github_installation_status
        != db_enums.GitHubInstallationStatus.ACTIVE.value
    ):
        return f"GitHub installation is {organization.github_installation_status}."
    return None


def _publish_github_in_progress(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
) -> None:
    """Open (or re-open) the single in-progress Check Run for this head SHA.

    Best-effort: any failure is logged and swallowed. The later completion
    (``publish`` / ``publish_failure``) finds this run by head SHA and updates
    it, so there is one check run per commit.
    """

    github_settings = _github_settings(settings)
    if not settings.github_publish_results or not github_settings.enabled:
        return
    try:
        analysis = session.get(db_models.Analysis, analysis_id)
        repository = (
            session.get(db_models.Repository, analysis.repository_id)
            if analysis is not None
            else None
        )
        if analysis is None or repository is None:
            return
        with stage("publish"):
            GitHubAnalysisPublisher(github_client).publish_in_progress(
                installation_id=_github_installation_id(
                    session=session,
                    analysis_id=analysis_id,
                    settings=settings,
                ),
                owner=repository.owner,
                repository_name=repository.name,
                head_sha=analysis.commit_sha,
                dashboard_url=settings.dashboard_analysis_url(analysis_id),
            )
    except Exception as exc:
        LOGGER.warning(
            "Could not publish in-progress GitHub Check Run: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(analysis_id), "outcome": "publish_error"},
        )


def _publish_github_failure(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    error: Exception,
) -> None:
    """Complete the check run so a crashed analysis never looks pending or passing."""

    github_settings = _github_settings(settings)
    if not settings.github_publish_results or not github_settings.enabled:
        return
    try:
        analysis = session.get(db_models.Analysis, analysis_id)
        repository = (
            session.get(db_models.Repository, analysis.repository_id)
            if analysis is not None
            else None
        )
        if analysis is None or repository is None:
            return
        publisher = GitHubAnalysisPublisher(github_client)
        if not hasattr(publisher, "publish_failure"):
            return
        publisher.publish_failure(
            installation_id=_github_installation_id(
                session=session,
                analysis_id=analysis_id,
                settings=settings,
            ),
            owner=repository.owner,
            repository_name=repository.name,
            head_sha=analysis.commit_sha,
            # Exception text can contain repository-controlled content and
            # credentials echoed by git/HTTP clients: redact, then keep it short.
            error_summary=redact_secrets(
                f"{error.__class__.__name__}: {error}", max_length=300
            ),
            dashboard_url=settings.dashboard_analysis_url(analysis_id),
        )
    except Exception as publish_exc:  # pragma: no cover - best effort
        LOGGER.warning(
            "Could not publish GitHub failure status: %s",
            redact_secrets(publish_exc),
            extra={"analysis_id": str(analysis_id), "outcome": "publish_error"},
        )


def _github_installation_id(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
) -> int:
    if settings.github_installation_id:
        return settings.github_installation_id
    analysis = session.get(db_models.Analysis, analysis_id)
    if analysis is None:
        msg = f"Analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    repository = session.get(db_models.Repository, analysis.repository_id)
    if repository is None:
        msg = f"Repository {analysis.repository_id} was not found."
        raise NotFoundError(msg)
    organization = session.get(db_models.Organization, repository.organization_id)
    if organization and organization.github_installation_id is not None:
        return organization.github_installation_id
    msg = "GITHUB_INSTALLATION_ID or organization.github_installation_id is required."
    raise ValidationError(msg)


def _github_report(
    session: Session,
    analysis_id,
    settings: WorkerSettings,
) -> GitHubAnalysisReport:
    analysis = session.get(db_models.Analysis, analysis_id)
    if analysis is None:
        msg = f"Analysis {analysis_id} was not found."
        raise NotFoundError(msg)
    repository = session.get(db_models.Repository, analysis.repository_id)
    pull_request = session.get(db_models.PullRequest, analysis.pull_request_id)
    confidence = (
        session.query(db_models.ConfidenceReport)
        .filter_by(analysis_id=analysis_id)
        .one_or_none()
    )
    if repository is None or pull_request is None or confidence is None:
        msg = f"GitHub publishing artifacts for analysis {analysis_id} are incomplete."
        raise NotFoundError(msg)
    dashboard_url = settings.dashboard_analysis_url(analysis_id)

    test_selection = (
        session.query(db_models.TestSelection)
        .filter_by(analysis_id=analysis_id)
        .one_or_none()
    )
    selected_tests_count = (
        len(test_selection.selected_tests) if test_selection else 0
    )

    discovered_tests_count = (
        selected_tests_count
        + len(getattr(test_selection, "skipped_tests", None) or ())
        if test_selection
        else 0
    )
    discovered_tests_count = max(
        discovered_tests_count,
        int(getattr(test_selection, "total_discovered_count", 0) or 0)
        if test_selection
        else 0,
    )
    # "Skipped" here means "not selected", which is NOT time saved unless the
    # full suite would otherwise have run. Do not present it as savings.
    skipped_tests_count = max(0, discovered_tests_count - selected_tests_count)

    affected_files = tuple(cf.path for cf in (analysis.changed_files or ()))
    evidence_items = list(getattr(confidence, "evidence_items", None) or ())
    verification_gaps = tuple(
        item.message
        for item in evidence_items
        if item.category == "analysis" and item.label == "verdict_gap"
    )
    unmapped_files = tuple(
        item.message
        for item in evidence_items
        if item.category == "analysis"
        and item.label in {"unmapped_changed_file", "unanalyzed_changed_file", "parse_failure"}
    )

    return GitHubAnalysisReport(
        analysis_id=analysis.id,
        owner=repository.owner,
        repository_name=repository.name,
        pull_request_number=pull_request.github_pr_number,
        head_sha=analysis.commit_sha,
        confidence_score=float(confidence.confidence_score),
        score_kind=CURRENT_SCORE_KIND.value,
        risk_level=confidence.risk_level.value,
        summary=confidence.summary,
        recommendations=tuple(confidence.recommendations),
        dashboard_url=dashboard_url,
        selected_tests_count=selected_tests_count,
        skipped_tests_count=skipped_tests_count,
        time_saved_percent=0.0,
        affected_files=affected_files,
        **_optional_report_fields(
            discovered_tests_count=discovered_tests_count,
            verification_gaps=verification_gaps,
            unmapped_files=unmapped_files,
        ),
        change_risk=confidence.change_risk,
        verification_status=confidence.verification_status,
        analysis_completeness=float(confidence.analysis_completeness) if confidence.analysis_completeness is not None else None,
    )


def _optional_report_fields(**fields) -> dict:
    """Pass only the report fields supported by the installed publisher."""

    supported = getattr(GitHubAnalysisReport, "__dataclass_fields__", {})
    return {key: value for key, value in fields.items() if key in supported}
