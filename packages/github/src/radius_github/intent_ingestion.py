"""Merge collected GitHub sources into an analysis' intent and build a snapshot (IN-02).

:class:`IntentIngestionService.apply` takes a :class:`Collection`, combines it
with the sources the analysis already has, and calls
``IntentSnapshotService.on_sources_changed``. The snapshot service already makes
that idempotent: sources whose ``(kind, id, raw_text_hash)`` and the criteria
extracted from them are unchanged produce **no** new version.

Merge rules (the only place they are written down):

* sources the collection does not mention are kept: the agent prompt, manual
  criteria and anything an engineer submitted through the intent API;
* ``PRESENT`` replaces the stored source with the same ``(kind, id)``;
* ``ABSENT`` removes an *owned* id (PR title/body, commits, linked issues,
  maintainer comments): GitHub is authoritative for them, so emptying the PR body
  or unlinking an issue retires its criteria through IN-06's carry-over rules. The
  spec file is not owned (see :func:`is_owned_source_id`);
* ``UNAVAILABLE`` keeps whatever is stored (an outage never orphans a confirmed
  criterion);
* on a ``complete`` collection, owned ids that were not looked up at all (an issue
  no longer linked, comments switched off) are removed too.

Persistence only goes through the ``IntentRepository`` and ``IntentSnapshotService``
ports; the caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from radius_intent.application import IntentSnapshotService
from radius_intent.domain import IntentSource
from radius_intent.interfaces import IntentRepository
from radius_shared.logging import get_logger

from radius_github.intent_sources import (
    Collection,
    PullRequestHint,
    SourceOutcome,
    SourceStatus,
    is_owned_source_id,
    pull_request_outcomes,
)

LOGGER = get_logger(__name__)

_Key = tuple[str, str]

#: Origin of outcomes that merely echo what the store already holds (the worker
#: reuses the webhook-recorded PR title/body). They must not overwrite an edit
#: that arrived while the worker was fetching.
STORED_ORIGIN = "stored"


@dataclass(frozen=True)
class IngestionReport:
    """What one ingestion did. Contains no source text."""

    analysis_id: str
    trigger: str
    outcomes: tuple[SourceOutcome, ...] = ()
    diagnostics: tuple[str, ...] = ()
    api_calls: int = 0
    complete: bool = False
    stopped_reason: str | None = None
    snapshot_version: int | None = None
    snapshot_created: bool = False
    sources_total: int = 0
    skipped: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def presence(self) -> dict[str, str]:
        """``{source_id: status}``: the RQ1 record of which sources exist."""
        return {o.source_id: o.status.value for o in self.outcomes}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable record (no text)."""
        return {
            "analysis_id": self.analysis_id,
            "trigger": self.trigger,
            "api_calls": self.api_calls,
            "complete": self.complete,
            "stopped_reason": self.stopped_reason,
            "snapshot_version": self.snapshot_version,
            "snapshot_created": self.snapshot_created,
            "sources_total": self.sources_total,
            "skipped": self.skipped,
            "diagnostics": list(self.diagnostics),
            "sources": [o.describe() for o in self.outcomes],
            **self.extra,
        }


class IntentIngestionService:
    """Apply collected sources to an analysis' intent."""

    def __init__(
        self,
        repository: IntentRepository,
        snapshots: IntentSnapshotService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._snapshots = snapshots
        self._clock = clock

    def current_sources(
        self, organization_id: UUID, analysis_id: str
    ) -> tuple[IntentSource, ...]:
        """Return the stored sources the latest snapshot is built from."""
        latest = self._snapshots.latest(organization_id, analysis_id)
        if latest is None:
            return ()
        stored = {
            (s.kind.value, s.source_id, s.raw_text_hash): s
            for s in self._repo.get_sources(organization_id, analysis_id)
        }
        return tuple(
            stored[key]
            for ref in latest.sources
            if (key := (ref.kind.value, ref.source_id, ref.raw_text_hash)) in stored
        )

    def apply(
        self,
        organization_id: UUID,
        analysis_id: str,
        collection: Collection,
        *,
        trigger: str,
    ) -> IngestionReport:
        """Merge ``collection`` into the analysis and build a snapshot if it changed."""
        current = self.current_sources(organization_id, analysis_id)
        merged: dict[_Key, IntentSource] = {
            (s.kind.value, s.source_id): s for s in current
        }
        mentioned: set[_Key] = set()
        for outcome in collection.outcomes:
            key = (outcome.kind.value, outcome.source_id)
            mentioned.add(key)
            if outcome.status is SourceStatus.PRESENT and outcome.source is not None:
                if outcome.origin == STORED_ORIGIN and key in merged:
                    continue  # re-read from the store: never overwrite a newer edit
                merged[key] = outcome.source
            elif outcome.status is SourceStatus.ABSENT and is_owned_source_id(
                outcome.source_id, outcome.kind
            ):
                merged.pop(key, None)
        if collection.complete:
            for key in [
                k
                for k, s in merged.items()
                if k not in mentioned and is_owned_source_id(s.source_id, s.kind)
            ]:
                del merged[key]
        final = tuple(merged.values())

        report = IngestionReport(
            analysis_id=analysis_id,
            trigger=trigger,
            outcomes=collection.outcomes,
            diagnostics=collection.diagnostics,
            api_calls=collection.api_calls,
            complete=collection.complete,
            stopped_reason=collection.stopped_reason,
            sources_total=len(final),
        )
        if not final and not current:
            report = replace(report, skipped="no_sources")
        else:
            result = self._snapshots.on_sources_changed(
                analysis_id, organization_id, final, self._clock(), trigger=trigger
            )
            report = replace(
                report,
                snapshot_version=result.snapshot.version,
                snapshot_created=result.created,
            )
        _log(report)
        return report

    def apply_pull_request_payload(
        self,
        organization_id: UUID,
        analysis_id: str,
        hint: PullRequestHint,
        *,
        reference: str,
        trigger: str,
    ) -> IngestionReport:
        """Store PR title/body from a webhook payload (no network, not ``complete``)."""
        now = self._clock()
        title, body = pull_request_outcomes(
            hint.title, hint.body, now=now, origin="webhook_payload", reference=reference
        )
        collection = Collection(outcomes=(title, body), fetched_at=now)
        return self.apply(organization_id, analysis_id, collection, trigger=trigger)


def _log(report: IngestionReport) -> None:
    """One structured record per ingestion (the 'which sources exist' data)."""
    LOGGER.info(
        "Intent ingestion",
        extra={
            "analysis_id": report.analysis_id,
            "intent_trigger": report.trigger,
            "intent_sources": report.presence(),
            "intent_api_calls": report.api_calls,
            "intent_snapshot_version": report.snapshot_version,
            "intent_snapshot_created": report.snapshot_created,
            "intent_stopped_reason": report.stopped_reason,
            "intent_diagnostics": list(report.diagnostics),
        },
    )


__all__ = ["STORED_ORIGIN", "IngestionReport", "IntentIngestionService"]
