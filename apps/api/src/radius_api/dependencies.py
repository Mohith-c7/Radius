"""FastAPI dependency wiring for Radius services."""

import importlib.util
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    InMemoryAnalysisStore,
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
)
from radius_confidence.application import (
    ConfidenceApplicationService,
    CoverageApplicationService,
)
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
    InMemoryCoverageStore,
    SqlAlchemyConfidenceStore,
    SqlAlchemyCoverageStore,
)
from radius_github import GitHubAppClient, GitHubAppSettings
from radius_github.intent_ingestion import IntentIngestionService
from radius_graph.infrastructure import InMemoryGraphStore, SqlAlchemyGraphStore
from radius_intent.application import IntentSnapshotService
from radius_intent.infrastructure import (
    InMemoryIntentRepository,
    SqlAlchemyIntentRepository,
    default_extractors,
)
from radius_intent.infrastructure.llm import (
    EnvEgressPolicy,
    InMemoryResponseCache,
    InMemoryUsageLedger,
    LlmCriterionExtractor,
    LlmExtractionConfig,
    LlmProvider,
)
from radius_intent.infrastructure.llm.anthropic_provider import (
    API_KEY_ENV,
    AnthropicProvider,
)
from radius_intent.infrastructure.testability import DeterministicTestabilityRater
from radius_intent.interfaces import (
    CriterionExtractor,
    IntentRepository,
    TestabilityRater,
)
from radius_repository.application import RepositoryApplicationService
from radius_repository.infrastructure import (
    InMemoryRepositoryStore,
    SqlAlchemyRepositoryStore,
)
from radius_shared.database.session import (
    create_database_engine,
    create_session_factory,
)
from radius_shared.logging import get_logger
from radius_shared.verdict_v2_repository import (
    InMemoryVerdictV2Repository,
    SqlVerdictV2Repository,
)
from radius_testing.application import TestingApplicationService
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    SqlAlchemyTestStore,
    StaticTestCommandPlanner,
)
from radius_worker.queue import InMemoryAnalysisQueue
from sqlalchemy.orm import Session, sessionmaker

from radius_api.api_keys import InMemoryApiKeyStore
from radius_api.idempotency import (
    InMemoryIdempotencyStore,
    SqlAlchemyIdempotencyStore,
)
from radius_api.intent_management import IntentManagementService

_LOG = get_logger("radius.api.intent")
_UNSET: Any = object()


def _default_llm_provider(config: LlmExtractionConfig) -> LlmProvider | None:
    """Build the Anthropic provider, or return ``None`` (fail closed, logged)."""

    if importlib.util.find_spec("anthropic") is None:
        _LOG.warning(
            "LLM intent extraction is enabled but the 'anthropic' package is "
            "not installed (extra 'llm'); the LLM extractor is disabled."
        )
        return None
    if not os.environ.get(API_KEY_ENV, "").strip():
        _LOG.warning(
            "LLM intent extraction is enabled but %s is not set; the LLM "
            "extractor is disabled.",
            API_KEY_ENV,
        )
        return None
    return AnthropicProvider(config.model)


@dataclass(slots=True)
class AppContainer:
    """Application service container for API runtime wiring."""

    repository_store: InMemoryRepositoryStore = field(
        default_factory=InMemoryRepositoryStore
    )
    analysis_store: InMemoryAnalysisStore = field(default_factory=InMemoryAnalysisStore)
    analysis_queue: InMemoryAnalysisQueue = field(default_factory=InMemoryAnalysisQueue)
    graph_store: InMemoryGraphStore = field(default_factory=InMemoryGraphStore)
    test_store: InMemoryTestStore = field(default_factory=InMemoryTestStore)
    confidence_store: InMemoryConfidenceStore = field(
        default_factory=InMemoryConfidenceStore
    )
    coverage_store: InMemoryCoverageStore = field(
        default_factory=InMemoryCoverageStore
    )
    idempotency_store: InMemoryIdempotencyStore = field(
        default_factory=InMemoryIdempotencyStore
    )
    intent_repository: InMemoryIntentRepository = field(
        default_factory=InMemoryIntentRepository
    )
    api_key_store: InMemoryApiKeyStore = field(default_factory=InMemoryApiKeyStore)
    #: Verdict v2 alpha store and republish outbox (memory backend).
    verdict_v2_repository: InMemoryVerdictV2Repository = field(
        default_factory=InMemoryVerdictV2Repository
    )
    #: Criterion extractors used by the intent snapshot service, in priority
    #: order for ties. Append here to add one (for example the IN-04 LLM
    #: extractor); the API layer does not care which extractors run.
    intent_extractors: tuple[CriterionExtractor, ...] = field(
        default_factory=default_extractors
    )
    #: Testability rater applied by the snapshot service (IN-05 -> IN-06).
    intent_rater: TestabilityRater = field(default_factory=DeterministicTestabilityRater)
    #: IN-04 LLM extraction config (RADIUS_LLM_INTENT_*); default OFF.
    llm_config: LlmExtractionConfig = field(default_factory=LlmExtractionConfig.from_env)
    #: Builds the provider lazily on first need; ``None`` means unavailable.
    llm_provider_factory: Callable[[LlmExtractionConfig], LlmProvider | None] = (
        _default_llm_provider
    )
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    session_factory: sessionmaker[Session] | None = None
    _llm_provider: Any = field(default=_UNSET, repr=False)
    _llm_cache: InMemoryResponseCache | None = field(default=None, repr=False)
    _llm_ledger: InMemoryUsageLedger | None = field(default=None, repr=False)

    def llm_extractor_for(self, organization_id: str) -> CriterionExtractor | None:
        """Return an LLM extractor for ``organization_id``, or ``None``.

        Registered only when the deployment flag is on AND the org is allowed.
        The per-call egress gate inside the extractor still applies. A missing
        SDK or API key fails closed with a log line, never an exception.
        """

        policy = EnvEgressPolicy.from_config(self.llm_config)
        if not policy.egress_allowed(organization_id):
            return None
        try:
            if self._llm_provider is _UNSET:
                self._llm_provider = self.llm_provider_factory(self.llm_config)
            provider = self._llm_provider
        except Exception:  # noqa: BLE001 - fail closed, never break a request
            _LOG.warning("LLM provider construction failed; LLM extractor disabled.")
            self._llm_provider = None
            return None
        if provider is None:
            return None
        if self._llm_cache is None:
            self._llm_cache = InMemoryResponseCache(self.llm_config.cache_size)
            self._llm_ledger = InMemoryUsageLedger()
        return LlmCriterionExtractor(
            provider,
            organization_id=organization_id,
            config=self.llm_config,
            policy=policy,
            cache=self._llm_cache,
            ledger=self._llm_ledger,
        )

    def repository_service(self) -> RepositoryApplicationService:
        """Return repository application service."""

        return RepositoryApplicationService(self.repository_store)

    def analysis_service(self) -> AnalysisApplicationService:
        """Return analysis application service."""

        return AnalysisApplicationService(
            self.analysis_store,
            pipeline=self.analysis_queue,
        )

    def testing_service(self) -> TestingApplicationService:
        """Return testing application service."""

        return TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=self.test_store,
            planner=StaticTestCommandPlanner(),
        )

    def confidence_service(self) -> ConfidenceApplicationService:
        """Return confidence application service."""

        return ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=self.confidence_store,
        )

    def coverage_service(self) -> CoverageApplicationService:
        """Return coverage application service."""

        return CoverageApplicationService(
            scorer=DeterministicConfidenceScorer(),
            confidence_store=self.confidence_store,
            coverage_store=self.coverage_store,
        )


def build_intent_service(
    container: AppContainer, repository: IntentRepository
) -> IntentManagementService:
    """Wire the intent management service over ``repository``."""

    def snapshots_for(org: UUID) -> IntentSnapshotService:
        extractors = container.intent_extractors
        llm = container.llm_extractor_for(str(org))
        if llm is not None:
            extractors = (*extractors, llm)
        return IntentSnapshotService(
            repository, extractors, rater=container.intent_rater
        )

    return IntentManagementService(
        repository,
        IntentSnapshotService(
            repository, container.intent_extractors, rater=container.intent_rater
        ),
        clock=container.clock,
        snapshots_for=snapshots_for,
    )


def build_ingestion_service(
    container: AppContainer, repository: IntentRepository
) -> IntentIngestionService:
    """Wire the IN-02 ingestion service over ``repository`` (same extractors as the API)."""

    return IntentIngestionService(
        repository,
        IntentSnapshotService(
            repository, container.intent_extractors, rater=container.intent_rater
        ),
        clock=container.clock,
    )


def request_intent_repository(request: Request) -> IntentRepository:
    """Return the intent repository bound to this request's SQL session (or memory)."""

    container = get_container(request)
    session = getattr(request.state, "radius_db_session", None)
    if container.session_factory is None or session is None:
        return container.intent_repository
    return SqlAlchemyIntentRepository(session)


def get_container(request: Request) -> AppContainer:
    """Return the app service container."""

    return request.app.state.container


def configure_sql_storage(container: AppContainer, settings: Any) -> None:
    """Configure SQL-backed stores for production runtime."""

    engine = create_database_engine(settings)
    container.session_factory = create_session_factory(engine)


def _new_session(container: AppContainer) -> Session:
    if container.session_factory is None:
        msg = "SQL storage is not configured."
        raise RuntimeError(msg)
    return container.session_factory()


def _acquire_request_session(request: Request, container: AppContainer) -> Session:
    session = getattr(request.state, "radius_db_session", None)
    if session is None:
        session = _new_session(container)
        request.state.radius_db_session = session
        request.state.radius_db_session_depth = 0
        request.state.radius_db_session_failed = False
    request.state.radius_db_session_depth += 1
    return session


def _release_request_session(request: Request, *, failed: bool) -> None:
    request.state.radius_db_session_failed = (
        request.state.radius_db_session_failed or failed
    )
    request.state.radius_db_session_depth -= 1
    if request.state.radius_db_session_depth > 0:
        return

    session = request.state.radius_db_session
    try:
        if request.state.radius_db_session_failed:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()
        request.state.radius_db_session = None


def get_github_client() -> GitHubAppClient:
    """Return the GitHub App client for the pull-based routes.

    Built per request so a restarted API picks up changed credentials; tests
    and the smoke script override it with a client on a fake transport.
    """

    return GitHubAppClient(GitHubAppSettings())


def get_repository_service(request: Request):
    """Return repository application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.repository_service()
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield RepositoryApplicationService(SqlAlchemyRepositoryStore(session))
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_analysis_service(request: Request):
    """Return analysis application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.analysis_service()
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield AnalysisApplicationService(
            SqlAlchemyAnalysisStore(session),
            pipeline=SqlAlchemyAnalysisJobQueue(session),
        )
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_testing_service(request: Request):
    """Return testing application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.testing_service()
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=SqlAlchemyTestStore(session),
            planner=StaticTestCommandPlanner(),
        )
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_confidence_service(request: Request):
    """Return confidence application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.confidence_service()
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=SqlAlchemyConfidenceStore(session),
        )
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_coverage_service(request: Request):
    """Return coverage application service."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.coverage_service()
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield CoverageApplicationService(
            scorer=DeterministicConfidenceScorer(),
            confidence_store=SqlAlchemyConfidenceStore(session),
            coverage_store=SqlAlchemyCoverageStore(session),
        )
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_verdict_v2_repository(request: Request):
    """Return the verdict v2 repository (one SQL session per request, or memory)."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.verdict_v2_repository
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield SqlVerdictV2Repository(session)
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_intent_service(request: Request):
    """Return the intent management service (one SQL session per request)."""

    container = get_container(request)
    if container.session_factory is None:
        yield build_intent_service(container, container.intent_repository)
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield build_intent_service(container, SqlAlchemyIntentRepository(session))
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_graph_store(request: Request):
    """Return graph store."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.graph_store
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield SqlAlchemyGraphStore(session)
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_idempotency_store(request: Request):
    """Return idempotency store."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.idempotency_store
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield SqlAlchemyIdempotencyStore(session)
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)


def get_coverage_store(request: Request):
    """Return coverage store."""

    container = get_container(request)
    if container.session_factory is None:
        yield container.coverage_store
        return
    session = _acquire_request_session(request, container)
    failed = False
    try:
        yield SqlAlchemyCoverageStore(session)
    except Exception:
        failed = True
        raise
    finally:
        _release_request_session(request, failed=failed)
