"""Best-effort intent ingestion for one analysis (IN-02).

Runs in the worker right after a job is claimed and before the analysis itself.
It reads the pull request's intent sources from GitHub with the installation
token, merges them into the analysis' intent and builds a snapshot. Nothing in
here may fail the analysis: every error is caught, logged (secrets redacted) and
reported as ``None``.

It uses its own database session and transaction, so a failure cannot poison
the analysis session, and a successful ingestion is committed even if the
analysis later fails.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from radius_github import GitHubAppClient
from radius_github.intent_ingestion import (
    STORED_ORIGIN,
    IngestionReport,
    IntentIngestionService,
)
from radius_github.intent_rest import (
    CallBudget,
    EtagCache,
    GitHubRestReader,
    HttpTransport,
)
from radius_github.intent_sources import (
    PR_BODY_ID,
    PR_TITLE_ID,
    CollectorConfig,
    GitHubIntentCollector,
    RepoContext,
    SourceOutcome,
    SourceStatus,
)
from radius_intent.application import IntentSnapshotService
from radius_intent.domain import IntentSourceKind
from radius_intent.infrastructure import SqlAlchemyIntentRepository, default_extractors
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.logging import get_logger
from radius_shared.redaction import redact_secrets
from sqlalchemy.orm import Session, sessionmaker

from radius_worker.config import WorkerSettings

LOGGER = get_logger(__name__)

TRIGGER = "analysis.started"


def ingest_intent_best_effort(
    *,
    session_factory: sessionmaker[Session],
    analysis_id: Any,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    installation_id_for: Callable[[Session], int],
    transport: HttpTransport | None = None,
    etag_cache: EtagCache | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> IngestionReport | None:
    """Ingest intent sources for ``analysis_id``; return the report or ``None``.

    ``None`` means skipped (disabled, no credentials, inactive installation, no
    pull request number) or failed. Never raises.
    """
    if not settings.intent_ingestion_enabled:
        return None
    if not (settings.github_app_id and settings.github_app_private_key):
        return None
    try:
        with session_factory() as session:
            report = _ingest(
                session,
                analysis_id,
                settings,
                github_client,
                installation_id_for,
                transport,
                etag_cache,
                clock,
            )
            if report is None:
                return None
            session.commit()
            return report
    except Exception as exc:  # best-effort by contract
        LOGGER.warning(
            "Intent ingestion failed; the analysis continues without it: %s",
            redact_secrets(f"{type(exc).__name__}: {exc}"),
            extra={"analysis_id": str(analysis_id), "outcome": "intent_ingestion_error"},
        )
        return None


def _ingest(
    session: Session,
    analysis_id: Any,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    installation_id_for: Callable[[Session], int],
    transport: HttpTransport | None,
    etag_cache: EtagCache | None,
    clock: Callable[[], datetime],
) -> IngestionReport | None:
    analysis = session.get(db_models.Analysis, analysis_id)
    repository = (
        session.get(db_models.Repository, analysis.repository_id) if analysis else None
    )
    pull_request = (
        session.get(db_models.PullRequest, analysis.pull_request_id) if analysis else None
    )
    if analysis is None or repository is None or pull_request is None:
        return None
    organization = session.get(db_models.Organization, repository.organization_id)
    if (
        organization is not None
        and organization.github_installation_status
        != db_enums.GitHubInstallationStatus.ACTIVE.value
    ):
        LOGGER.info(
            "Intent ingestion skipped: installation is not active",
            extra={"analysis_id": str(analysis_id)},
        )
        return None
    if not pull_request.github_pr_number:
        return None

    installation_id = installation_id_for(session)
    tokens: list[str] = []

    def token_provider() -> str:
        if not tokens:
            tokens.append(github_client.create_installation_token(installation_id).token)
        return tokens[0]

    repo = SqlAlchemyIntentRepository(session)
    service = IntentIngestionService(
        repo,
        IntentSnapshotService(repo, default_extractors()),
        clock=clock,
    )
    collector = GitHubIntentCollector(
        GitHubRestReader(
            base_url=settings.github_api_base_url,
            api_version=settings.github_api_version,
            timeout_seconds=settings.github_timeout_seconds,
            transport=transport,
            cache=etag_cache,
        ),
        token_provider,
        config=CollectorConfig(
            include_issue_comments=settings.intent_include_issue_comments,
            allow_cross_repo=settings.intent_allow_cross_repo,
        ),
        clock=clock,
    )
    org_id = repository.organization_id
    ctx = RepoContext(
        owner=repository.owner,
        repo=repository.name,
        pr_number=pull_request.github_pr_number,
        head_sha=analysis.commit_sha,
        scope=str(installation_id),
    )
    collection = collector.collect(
        ctx,
        known_pr=_recorded_pr_outcomes(service, org_id, str(analysis_id)),
        budget=CallBudget(
            max_calls=settings.intent_max_api_calls,
            deadline_seconds=settings.intent_deadline_seconds,
        ),
    )
    return service.apply(org_id, str(analysis_id), collection, trigger=TRIGGER)


def _recorded_pr_outcomes(
    service: IntentIngestionService, org_id: Any, analysis_id: str
) -> tuple[SourceOutcome, SourceOutcome] | None:
    """Title/body the webhook already stored for this analysis, if both exist."""
    wanted = {
        (IntentSourceKind.PR_TITLE, PR_TITLE_ID),
        (IntentSourceKind.PR_BODY, PR_BODY_ID),
    }
    found: dict[str, SourceOutcome] = {}
    for source in service.current_sources(org_id, analysis_id):
        if (source.kind, source.source_id) in wanted:
            found[source.source_id] = SourceOutcome(
                source.kind,
                source.source_id,
                SourceStatus.PRESENT,
                None,
                source,
                STORED_ORIGIN,
            )
    if PR_TITLE_ID in found and PR_BODY_ID in found:
        return found[PR_TITLE_ID], found[PR_BODY_ID]
    return None


__all__ = ["TRIGGER", "ingest_intent_best_effort"]
