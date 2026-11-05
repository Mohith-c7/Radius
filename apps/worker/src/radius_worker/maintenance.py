"""Opt-in data-retention maintenance (``RADIUS_RETENTION_DAYS``).

Deletes only rows of clearly disposable tables once they are older than the retention
window:

* ``idempotency_keys``: stored API responses used for replay protection.
* ``verdict_v2_requests``: outbox rows that gave up (attempts exhausted). Completed
  requests are already deleted by the outbox on success, so only dead letters can linger.
* ``mutation_result_cache``: a pure cache of mutant results; a miss only costs a re-run.
* ``auth_sessions``, ``auth_tokens``, ``auth_oauth_flows`` (C-13): sign-in sessions, one-time
  tokens and OAuth flows that expired (or were revoked/used) more than the window ago. Only
  dead rows are removed; a live session is never touched. Skipped when the tables do not exist.

It NEVER touches analyses, verdicts, evidence, audit rows or anything else. Each table is
pruned in bounded batches (one commit per batch) so a large backlog cannot hold a long
transaction, and ``dry_run`` only counts what would be deleted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from radius_shared.database import models as db_models
from radius_shared.database.verdict_v2 import (
    MutationResultCacheRow,
    VerdictV2RequestRow,
)
from radius_shared.logging import get_logger
from sqlalchemy import delete, func, inspect, select
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


def _auth_table(name: str, *columns: str) -> sa.TableClause:
    """Lightweight handle on a sign-in table (its models live in the API app)."""

    return sa.table(
        name,
        sa.column("id", sa.String),
        *(sa.column(column, sa.DateTime(timezone=True)) for column in columns),
    )


_AUTH_SESSIONS = _auth_table("auth_sessions", "expires_at", "revoked_at")
_AUTH_TOKENS = _auth_table("auth_tokens", "expires_at", "used_at")
_AUTH_OAUTH_FLOWS = _auth_table("auth_oauth_flows", "expires_at")


def _id_column(model):
    return model.c.id if isinstance(model, sa.TableClause) else model.id


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
        (
            "auth_sessions",
            _AUTH_SESSIONS,
            (_AUTH_SESSIONS.c.expires_at < cutoff) | (_AUTH_SESSIONS.c.revoked_at < cutoff),
        ),
        (
            "auth_tokens",
            _AUTH_TOKENS,
            (_AUTH_TOKENS.c.expires_at < cutoff) | (_AUTH_TOKENS.c.used_at < cutoff),
        ),
        (
            "auth_oauth_flows",
            _AUTH_OAUTH_FLOWS,
            _AUTH_OAUTH_FLOWS.c.expires_at < cutoff,
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
            table_name = model.name if isinstance(model, sa.TableClause) else model.__tablename__
            if not inspect(session.get_bind()).has_table(table_name):
                continue  # e.g. the sign-in tables before the API first ran
            id_col = _id_column(model)
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
                            select(id_col).where(condition).limit(batch_size)
                        )
                    )
                    if not ids:
                        break
                    session.execute(delete(model).where(id_col.in_(ids)))
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
