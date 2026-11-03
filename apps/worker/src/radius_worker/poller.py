"""Opt-in pull request poller (no webhook needed).

With ``RADIUS_GITHUB_POLL_INTERVAL_SECONDS`` set (minimum 30), the worker lists the
open pull requests of every connected repository whose GitHub App installation it
can reach and starts an analysis for each head commit that has none yet. It runs
the same ``radius_github.pull_sync.sync_open_pull_requests`` as the API route
``sync-pull-requests``; the differences are policy only:

* failed or cancelled analyses are not retried automatically (``retry_failed=False``),
  so a head commit that cannot be analyzed is not re-queued on every tick;
* at most ``RADIUS_GITHUB_POLL_MAX_ANALYSES_PER_TICK`` analyses and
  ``RADIUS_GITHUB_POLL_MAX_REPOSITORIES_PER_TICK`` repositories per tick (the rest
  wait for the next tick; repositories rotate so none starves);
* one repository failing never stops the others, and a rate-limited installation is
  left alone until GitHub's reset time (GitHub calls already retry within a bounded
  budget in ``GitHubAppClient``);
* the interval and the first delay are jittered so several workers do not poll in
  lockstep.

Not done: conditional requests (ETag / If-None-Match) for the pull request listing.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.infrastructure import (
    SqlAlchemyAnalysisJobQueue,
    SqlAlchemyAnalysisStore,
)
from radius_github import GitHubAppClient, GitHubRateLimitError
from radius_github.pull_sync import sync_open_pull_requests
from radius_repository.application import RepositoryApplicationService
from radius_repository.infrastructure import SqlAlchemyRepositoryStore
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.logging import get_logger
from radius_shared.redaction import redact_secrets
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radius_worker.config import WorkerSettings

LOGGER = get_logger(__name__)

#: Never wait longer than this for a rate-limited installation, whatever GitHub asks.
MAX_RATE_LIMIT_BACKOFF_SECONDS = 900.0
JITTER_FRACTION = 0.1


@dataclass(slots=True)
class PollSummary:
    """What one tick did (also logged)."""

    repositories: int = 0
    started: int = 0
    deferred: int = 0
    skipped: int = 0
    errors: int = 0
    rate_limited_installations: int = 0
    analysis_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Target:
    repository_id: UUID
    installation_id: int


class PullRequestPoller:
    """Polls connected repositories; call :meth:`poll_once` every :meth:`next_delay`."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        github_client: GitHubAppClient,
        settings: WorkerSettings,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._session_factory = session_factory
        self._github = github_client
        self._settings = settings
        self._rng = rng
        self._clock = clock
        self._should_stop = should_stop
        self._cursor = 0
        self._backoff_until: dict[int, float] = {}

    @property
    def interval(self) -> float:
        return self._settings.github_poll_interval_seconds

    @property
    def enabled(self) -> bool:
        return self.interval > 0

    def first_delay(self) -> float:
        """Spread the first tick of several workers over the interval."""

        return self.interval * (0.1 + 0.9 * self._rng())

    def next_delay(self) -> float:
        """The interval, plus or minus ``JITTER_FRACTION`` of it."""

        return self.interval * (1 + JITTER_FRACTION * (2 * self._rng() - 1))

    # -- one tick ---------------------------------------------------------------
    def poll_once(self) -> PollSummary:
        """List open pull requests of connected repositories and queue new head commits.

        Never raises: every failure is logged and counted.
        """

        started_at = self._clock()
        summary = PollSummary()
        try:
            targets = self._targets()
        except Exception as exc:  # noqa: BLE001 - the loop must survive a database blip
            LOGGER.warning(
                "GitHub poll could not list repositories; will retry next tick",
                extra={"outcome": "poll_error", "error": redact_secrets(exc)},
            )
            summary.errors += 1
            return summary

        budget = self._settings.github_poll_max_analyses_per_tick
        tokens: dict[int, str | None] = {}
        limited: set[int] = set()
        for target in targets:
            if self._should_stop():
                break
            if target.installation_id in limited or self._backed_off(
                target.installation_id
            ):
                limited.add(target.installation_id)
                continue
            if budget <= 0:
                summary.deferred += 1
                continue
            try:
                token = self._token(tokens, target.installation_id)
                self._poll_repository(target, token, budget, summary)
            except GitHubRateLimitError as exc:
                limited.add(target.installation_id)
                wait = min(
                    exc.retry_after_seconds or 60.0, MAX_RATE_LIMIT_BACKOFF_SECONDS
                )
                self._backoff_until[target.installation_id] = self._clock() + wait
                LOGGER.warning(
                    "GitHub poll rate limited; skipping this installation for %.0fs",
                    wait,
                    extra={
                        "outcome": "poll_rate_limited",
                        "installation_id": target.installation_id,
                        "repository_id": str(target.repository_id),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - one repository must not stop the others
                summary.errors += 1
                LOGGER.warning(
                    "GitHub poll failed for one repository; continuing",
                    extra={
                        "outcome": "poll_repository_error",
                        "repository_id": str(target.repository_id),
                        "installation_id": target.installation_id,
                        "error": redact_secrets(exc),
                    },
                )
            budget = self._settings.github_poll_max_analyses_per_tick - summary.started
        summary.rate_limited_installations = len(limited)
        LOGGER.info(
            "GitHub poll tick finished",
            extra={
                "outcome": "poll_tick",
                "repositories": summary.repositories,
                "analyses_started": summary.started,
                "deferred": summary.deferred,
                "skipped": summary.skipped,
                "errors": summary.errors,
                "rate_limited_installations": summary.rate_limited_installations,
                "duration_ms": int((self._clock() - started_at) * 1000),
            },
        )
        return summary

    # -- internals ----------------------------------------------------------------
    def _backed_off(self, installation_id: int) -> bool:
        until = self._backoff_until.get(installation_id)
        if until is None:
            return False
        if self._clock() >= until:
            del self._backoff_until[installation_id]
            return False
        return True

    def _targets(self) -> list[_Target]:
        """Connected repositories with a usable installation, rotated for fairness."""

        forced = self._settings.github_installation_id
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    db_models.Repository.id,
                    db_models.Organization.github_installation_id,
                    db_models.Organization.github_installation_status,
                )
                .join(
                    db_models.Organization,
                    db_models.Organization.id == db_models.Repository.organization_id,
                )
                .where(
                    db_models.Repository.status
                    != db_enums.RepositoryStatus.DISCONNECTED
                )
                .order_by(db_models.Repository.id)
            ).all()
        targets: list[_Target] = []
        for repository_id, installation_id, installation_status in rows:
            if installation_status != db_enums.GitHubInstallationStatus.ACTIVE.value:
                continue
            effective = forced or installation_id
            if effective:
                targets.append(_Target(UUID(str(repository_id)), int(effective)))
        if not targets:
            return targets
        limit = self._settings.github_poll_max_repositories_per_tick
        start = self._cursor % len(targets)
        rotated = targets[start:] + targets[:start]
        chosen = rotated[:limit]
        self._cursor = (start + len(chosen)) % len(targets)
        return chosen

    def _token(self, cache: dict[int, str | None], installation_id: int) -> str:
        token = cache.get(installation_id)
        if token is None:
            token = self._github.create_installation_token(installation_id).token
            cache[installation_id] = token
        return token

    def _poll_repository(
        self, target: _Target, token: str, budget: int, summary: PollSummary
    ) -> None:
        with self._session_factory() as session:
            repository_service = RepositoryApplicationService(
                SqlAlchemyRepositoryStore(session)
            )
            analysis_service = AnalysisApplicationService(
                SqlAlchemyAnalysisStore(session),
                pipeline=SqlAlchemyAnalysisJobQueue(session),
            )
            repository = repository_service.get_repository(target.repository_id)
            raw = self._github.list_pull_requests(
                token=token, owner=repository.owner, repo=repository.name, state="open"
            )
            try:
                outcome = sync_open_pull_requests(
                    repository_service=repository_service,
                    analysis_service=analysis_service,
                    repository=repository,
                    raw_pull_requests=raw,
                    retry_failed=False,
                    max_analyses=budget,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        summary.repositories += 1
        summary.started += len(outcome.analysis_ids)
        summary.deferred += len(outcome.deferred)
        summary.skipped += len(outcome.skipped)
        summary.analysis_ids.extend(outcome.analysis_ids)
        if outcome.analysis_ids or outcome.skipped:
            LOGGER.info(
                "GitHub poll queued analyses",
                extra={
                    "outcome": "poll_repository",
                    "repository_id": str(target.repository_id),
                    "full_name": f"{repository.owner}/{repository.name}",
                    "analysis_ids": outcome.analysis_ids,
                    "skipped": outcome.skipped,
                },
            )
