"""Opt-in data-retention maintenance (``RADIUS_RETENTION_DAYS``).

Deletes only rows of clearly disposable tables once they are older than the retention
window:

* ``idempotency_keys``: stored API responses used for replay protection.
* ``verdict_v2_requests``: outbox rows that gave up (attempts exhausted). Completed
  requests are already deleted by the outbox on success, so only dead letters can linger.
* ``mutation_result_cache``: a pure cache of mutant results; a miss only costs a re-run.

It NEVER touches analyses, verdicts, evidence, audit rows or anything else. Each table is
pruned in bounded batches (one commit per batch) so a large backlog cannot hold a long
transaction, and ``dry_run`` only counts what would be deleted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from radius_shared.database import models as db_models
from radius_shared.database.verdict_v2 import (
    MutationResultCacheRow,
    VerdictV2RequestRow,
)
from radius_shared.logging import get_logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

LOGGER = get_logger(__name__)

MIN_RETENTION_DAYS = 7
DEFAULT_BATCH_SIZE = 500
#: Upper bound of batches per table per pass; the rest is picked up on the next pass.
MAX_BATCHES_PER_TABLE = 20
#: Outbox rows with at least this many attempts are never claimed again (dead letters).
OUTBOX_MAX_ATTEMPTS = 5


@dataclass
class RetentionReport:
    """Rows deleted (or, in a dry run, that would be deleted) per table."""

    dry_run: bool
    cutoff: datetime
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def normalise_retention_days(value: object) -> int:
    """0, negative or unparsable mean off; 1 to 6 are raised to MIN_RETENTION_DAYS."""

    try:
        days = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    return max(days, MIN_RETENTION_DAYS)


def _targets(cutoff: datetime):
    """(name, model, condition) triples: the only tables retention may delete from."""

    return (
        (
            "idempotency_keys",
            db_models.IdempotencyKey,
            db_models.IdempotencyKey.created_at < cutoff,
        ),
        (
            "verdict_v2_requests",
            VerdictV2RequestRow,
            (VerdictV2RequestRow.requested_at < cutoff)
            & (VerdictV2RequestRow.attempts >= OUTBOX_MAX_ATTEMPTS),
        ),
        (
            "mutation_result_cache",
            MutationResultCacheRow,
            MutationResultCacheRow.created_at < cutoff,
        ),
    )


def run_retention(
    session_factory: Callable[[], Session],
    *,
    retention_days: int,
    dry_run: bool = False,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batches: int = MAX_BATCHES_PER_TABLE,
) -> RetentionReport:
    """Run one retention pass. A ``retention_days`` below the minimum is raised to it.

    Returns a report; ``retention_days`` of 0 (off) deletes and counts nothing.
    """

    days = normalise_retention_days(retention_days)
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    report = RetentionReport(dry_run=dry_run, cutoff=cutoff)
    if days == 0:
        return report

    for name, model, condition in _targets(cutoff):
        deleted = 0
        with session_factory() as session:
            if dry_run:
                deleted = int(
                    session.scalar(
                        select(func.count()).select_from(model).where(condition)
                    )
                    or 0
                )
            else:
                for _ in range(max_batches):
                    ids = list(
                        session.scalars(
                            select(model.id).where(condition).limit(batch_size)
                        )
                    )
                    if not ids:
                        break
                    session.execute(delete(model).where(model.id.in_(ids)))
                    session.commit()
                    deleted += len(ids)
                    if len(ids) < batch_size:
                        break
        report.counts[name] = deleted

    LOGGER.info(
        "Retention dry run: rows that would be deleted"
        if dry_run
        else "Retention pass finished",
        extra={
            "outcome": "retention_dry_run" if dry_run else "retention_done",
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "counts": dict(report.counts),
        },
    )
    return report
