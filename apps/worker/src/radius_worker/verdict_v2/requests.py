"""Outbox consumer for republish after CI (VS-07); table ``verdict_v2_requests``.

The API upserts one row per analysis when CI results arrive (it holds no GitHub
credentials). ``process_pending`` runs inside the worker poll loop:

1. claim the oldest available request (own transaction, committed at once, so
   the claim is visible to other workers);
2. recompute Stage B from the stored Stage A bundle (no clone) through the
   injected ``Recomputer``;
3. publish the newest stored verdict when the flag is ``on`` (idempotent: an
   identical rendered body is not re-sent; stale heads are never published);
4. delete the request only if it was not re-requested meanwhile; on any error
   release it with exponential backoff (``attempts`` is capped).

A bounded sweep (``reconcile_stale``, B-09) re-queues analyses whose newest CI upload is
newer than their newest verdict and that have no queued request: the API swallows enqueue
failures after the upload is committed, so without the sweep a transient database error
would leave the verdict on "awaiting CI results" while CI is red.

Flag ``off``: nothing is claimed. ``shadow``: recompute and store, never publish.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from radius_github.client import GitHubAppClient
from radius_github.verdict_v2.ports import VerdictRenderer
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_repository import RequestClaim, SqlVerdictV2Repository
from sqlalchemy.orm import Session, sessionmaker

from radius_worker.config import WorkerSettings
from radius_worker.verdict_v2 import publish as publish_module

LOGGER = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300.0
RECONCILE_INTERVAL_SECONDS = 60.0
RECONCILE_LIMIT = 20
_last_reconcile = 0.0  # monotonic seconds; one sweep per interval per process


class Recomputer(Protocol):
    """Rebuild and store the Stage B bundle of one analysis (VS-06 ``scoring``).

    Returns True when the newest stored revision changed.
    """

    def recompute(
        self, session: Session, organization_id: UUID, analysis_id: UUID
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class RequestResult:
    analysis_id: UUID
    status: str  # done | retry | dropped
    detail: str


@dataclass(slots=True)
class PendingSummary:
    processed: int = 0
    results: list[RequestResult] = field(default_factory=list)


def reconcile_stale(
    session_factory: sessionmaker[Session],
    *,
    now: datetime | None = None,
    limit: int = RECONCILE_LIMIT,
    grace_seconds: float = 300.0,
) -> int:
    """Queue a recompute for analyses with CI uploads newer than their verdict; never raises."""

    try:
        with session_factory() as session:
            repo = SqlVerdictV2Repository(session)
            stale = repo.stale_analyses(now=now, grace_seconds=grace_seconds, limit=limit)
            for org, analysis in stale:
                repo.enqueue_request(org, analysis, "ci_results", now=now)
            session.commit()
            return len(stale)
    except Exception as exc:
        LOGGER.warning(
            "Verdict v2 reconcile failed: %s",
            redact_secrets(exc),
            extra={"outcome": "verdict_v2_reconcile_error"},
        )
        return 0


def _maybe_reconcile(session_factory: sessionmaker[Session], now: datetime | None) -> None:
    global _last_reconcile  # noqa: PLW0603
    tick = time.monotonic()
    if now is None and tick - _last_reconcile < RECONCILE_INTERVAL_SECONDS:
        return
    _last_reconcile = tick
    reconcile_stale(session_factory, now=now)


def process_pending(
    *,
    session_factory: sessionmaker[Session],
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    recomputer: Recomputer | None = None,
    renderer: VerdictRenderer | None = None,
    max_requests: int = 10,
    now: datetime | None = None,
) -> PendingSummary:
    """Consume up to ``max_requests`` outbox rows; never raises."""

    summary = PendingSummary()
    if settings.verdict_v2_mode == VerdictV2Mode.OFF:
        return summary
    _maybe_reconcile(session_factory, now)
    for _ in range(max_requests):
        try:
            with session_factory() as session:
                claim = SqlVerdictV2Repository(session).claim_request(
                    now=now, lease_seconds=LEASE_SECONDS, max_attempts=MAX_ATTEMPTS
                )
                session.commit()
        except Exception as exc:
            LOGGER.warning(
                "Verdict v2 outbox claim failed: %s",
                redact_secrets(exc),
                extra={"outcome": "verdict_v2_claim_error"},
            )
            break
        if claim is None:
            break
        summary.processed += 1
        summary.results.append(
            _handle(
                claim,
                session_factory=session_factory,
                settings=settings,
                github_client=github_client,
                recomputer=recomputer,
                renderer=renderer,
                now=now,
            )
        )
    return summary


def _handle(
    claim: RequestClaim,
    *,
    session_factory: sessionmaker[Session],
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    recomputer: Recomputer | None,
    renderer: VerdictRenderer | None,
    now: datetime | None,
) -> RequestResult:
    extra = {"analysis_id": str(claim.analysis_id), "attempt": claim.attempts}
    try:
        with session_factory() as session:
            if recomputer is not None:
                recomputer.recompute(session, claim.organization_id, claim.analysis_id)
            outcome = publish_module.publish_latest(
                session,
                organization_id=claim.organization_id,
                analysis_id=claim.analysis_id,
                settings=settings,
                github_client=github_client,
                renderer=renderer if renderer is not None else publish_module.load_renderer(),
            )
            session.commit()
        with session_factory() as session:
            completed = SqlVerdictV2Repository(session).complete_request(claim)
            session.commit()
    except Exception as exc:
        LOGGER.warning(
            "Verdict v2 request failed (attempt %s): %s",
            claim.attempts,
            redact_secrets(exc),
            extra={**extra, "outcome": "verdict_v2_request_error"},
        )
        _release(session_factory, claim, exc, now)
        if isinstance(exc, publish_module.PublishError):
            _record_publish_error(session_factory, exc)
        return RequestResult(claim.analysis_id, "retry", redact_secrets(exc, max_length=200))
    LOGGER.info(
        "Verdict v2 request processed",
        extra={**extra, "outcome": outcome.status, "reason": outcome.reason},
    )
    return RequestResult(
        claim.analysis_id,
        "done" if completed else "retry",
        f"{outcome.status}:{outcome.reason}",
    )


def _release(
    session_factory: sessionmaker[Session],
    claim: RequestClaim,
    error: Exception,
    now: datetime | None,
) -> None:
    try:
        with session_factory() as session:
            SqlVerdictV2Repository(session).fail_request(claim, error, now=now)
            session.commit()
    except Exception as exc:  # pragma: no cover - best effort
        LOGGER.warning(
            "Could not release verdict v2 request: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(claim.analysis_id)},
        )


def _record_publish_error(
    session_factory: sessionmaker[Session], error: publish_module.PublishError
) -> None:
    try:
        with session_factory() as session:
            SqlVerdictV2Repository(session).record_publish_error(
                error.organization_id, error.row_id, error
            )
            session.commit()
    except Exception as exc:  # pragma: no cover - best effort
        LOGGER.warning(
            "Could not record verdict v2 publish error: %s", redact_secrets(exc)
        )
