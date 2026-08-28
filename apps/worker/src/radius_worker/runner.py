"""Worker runtime shell."""

import time
from collections.abc import Callable
from dataclasses import dataclass
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
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
    SqlAlchemyConfidenceStore,
)
from radius_github import GitHubAnalysisPublisher, GitHubAppClient, GitHubAppSettings
from radius_github.publisher import GitHubAnalysisReport
from radius_graph.application import GraphApplicationService
from radius_graph.infrastructure import InMemoryGraphStore, SqlAlchemyGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_repository.infrastructure import LocalGitRepositoryClient
from radius_shared.database import models as db_models
from radius_shared.database.session import (
    create_database_engine,
    create_session_factory,
)
from radius_shared.errors import NotFoundError, ValidationError
from radius_shared.logging import configure_logging, get_logger
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
from radius_worker.orchestrator import (
    ExecuteAnalysisCommand,
    Phase1AnalysisOrchestrator,
)
from radius_worker.queue import InMemoryAnalysisQueue

LOGGER = get_logger(__name__)


def run_worker() -> None:
    """Start the SQL-backed worker process."""

    settings = WorkerSettings()
    configure_logging(settings.log_level)
    runtime = create_sql_worker_runtime(settings)
    print("Radius worker ready")
    runtime.run_loop(poll_interval_seconds=settings.poll_interval_seconds)


@dataclass(slots=True)
class SqlAlchemyWorkerRuntime:
    """SQL-backed worker runtime with explicit transaction boundaries."""

    session_factory: sessionmaker[Session]
    repository_cache_dir: Path
    git_client: LocalGitRepositoryClient
    settings: WorkerSettings
    github_client: GitHubAppClient

    def run_once(self) -> bool:
        """Claim and execute one durable analysis job."""

        job = self._claim_job()
        if job is None:
            return False
        try:
            with self.session_factory() as session:
                orchestrator = _create_sql_orchestrator(session)
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
                _publish_github_result(
                    session=session,
                    analysis_id=job.analysis_id,
                    settings=self.settings,
                    github_client=self.github_client,
                )
                self._queue(session).complete(job.analysis_id)
                session.commit()
        except Exception as exc:
            LOGGER.exception(
                "Analysis job failed",
                extra={"analysis_id": str(job.analysis_id)},
            )
            with self.session_factory() as session:
                queue = self._queue(session)
                if job.attempts >= self.settings.job_max_attempts:
                    queue.fail(job.analysis_id, str(exc))
                else:
                    queue.requeue(job.analysis_id, str(exc))
                session.commit()
            raise
        return True

    def run_loop(
        self,
        *,
        poll_interval_seconds: float = 2.0,
        stop_after_idle_cycles: int | None = None,
    ) -> None:
        """Run the SQL-backed polling loop."""

        idle_cycles = 0
        while True:
            processed = self.run_once()
            if processed:
                idle_cycles = 0
                continue
            idle_cycles += 1
            if (
                stop_after_idle_cycles is not None
                and idle_cycles >= stop_after_idle_cycles
            ):
                return
            time.sleep(poll_interval_seconds)

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

    engine = create_database_engine(settings)
    return SqlAlchemyWorkerRuntime(
        session_factory=create_session_factory(engine),
        repository_cache_dir=settings.repository_cache_dir,
        git_client=LocalGitRepositoryClient(),
        settings=settings,
        github_client=GitHubAppClient(_github_settings(settings)),
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
    git_client.checkout(repository_path, analysis.commit_sha)
    return ExecuteAnalysisCommand(
        analysis_id=analysis.id,
        repository_id=repository.id,
        repository_path=repository_path,
        base_ref=f"origin/{pull_request.target_branch}",
        head_ref=analysis.commit_sha,
    )


def _create_sql_orchestrator(session: Session) -> Phase1AnalysisOrchestrator:
    graph_store = SqlAlchemyGraphStore(session)
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
            runner=SubprocessTestRunner(),
        ),
        confidence_service=ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=SqlAlchemyConfidenceStore(session),
        ),
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
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    )


def _github_settings(settings: WorkerSettings) -> GitHubAppSettings:
    return GitHubAppSettings(
        RADIUS_ENV=settings.environment,
        RADIUS_LOG_LEVEL=settings.log_level,
        GITHUB_APP_ID=settings.github_app_id,
        GITHUB_APP_PRIVATE_KEY=settings.github_app_private_key,
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
    return (f"Authorization: Bearer {token}",)


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
    installation_id = _github_installation_id(
        session=session,
        analysis_id=analysis_id,
        settings=settings,
    )
    report = _github_report(session, analysis_id, settings)
    GitHubAnalysisPublisher(github_client).publish(
        installation_id=installation_id,
        report=report,
    )


def _github_installation_id(
    *,
    session: Session,
    analysis_id,
    settings: WorkerSettings,
) -> int:
    if settings.github_installation_id is not None:
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
    confidence = session.query(db_models.ConfidenceReport).filter_by(
        analysis_id=analysis_id
    ).one_or_none()
    if repository is None or pull_request is None or confidence is None:
        msg = f"GitHub publishing artifacts for analysis {analysis_id} are incomplete."
        raise NotFoundError(msg)
    dashboard_url = (
        f"{settings.dashboard_base_url.rstrip('/')}/analyses/{analysis_id}"
        if settings.dashboard_base_url
        else None
    )
    return GitHubAnalysisReport(
        analysis_id=analysis.id,
        owner=repository.owner,
        repository_name=repository.name,
        pull_request_number=pull_request.github_pr_number,
        head_sha=analysis.commit_sha,
        confidence_score=float(confidence.confidence_score),
        risk_level=confidence.risk_level.value,
        summary=confidence.summary,
        recommendations=tuple(confidence.recommendations),
        dashboard_url=dashboard_url,
    )
