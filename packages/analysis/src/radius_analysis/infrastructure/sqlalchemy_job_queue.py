"""SQLAlchemy-backed durable analysis job queue."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.observability import current_traceparent, span
from radius_shared.redaction import redact_secrets
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

LOGGER = logging.getLogger(__name__)

#: ``analysis_jobs.last_error`` is user-visible (API/dashboard); keep it short.
MAX_ERROR_LENGTH = 2000

_ACTIVE_ANALYSIS_STATUSES = (
    db_enums.AnalysisStatus.PENDING,
    db_enums.AnalysisStatus.RUNNING,
)
_TERMINAL_ANALYSIS_STATUSES = frozenset(
    {
        db_enums.AnalysisStatus.COMPLETED,
        db_enums.AnalysisStatus.FAILED,
        db_enums.AnalysisStatus.CANCELLED,
    }
)

EXHAUSTED_ATTEMPTS_ERROR = "Job exceeded maximum retry attempts."
CANCELLED_PREFIX = "Cancelled: "


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    """Durable analysis job DTO."""

    id: UUID
    analysis_id: UUID
    status: str
    attempts: int
    last_error: str | None
    locked_at: datetime | None
    traceparent: str | None = None
    claimed_by: str | None = None
    available_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReapedAnalysis:
    """An analysis the reaper moved to ``failed`` because it could not finish."""

    analysis_id: UUID
    job_id: UUID | None
    reason: str


def _lease_is_live(job: db_models.AnalysisJob | None, lease_cutoff: datetime) -> bool:
    """True when ``job`` is running under a lease renewed since ``lease_cutoff`` (C-18)."""

    return (
        job is not None
        and job.status == db_enums.AnalysisJobStatus.RUNNING
        and job.claimed_by is not None
        and job.locked_at is not None
        and _as_utc(job.locked_at) >= lease_cutoff
    )


def _deadline_reference(
    analysis: db_models.Analysis, job: db_models.AnalysisJob | None
) -> datetime:
    """Where the analysis deadline is counted from: the job's last change (queued, claimed,
    heartbeat, requeued), or the analysis start when it has no job (C-18)."""

    if job is None:
        return _as_utc(analysis.started_at)
    candidates = [job.updated_at, job.created_at, job.available_at, job.locked_at]
    return max(_as_utc(c) for c in candidates if c is not None)


class SqlAlchemyAnalysisJobQueue:
    """Durable FIFO queue for analysis execution."""

    def __init__(
        self,
        session: Session,
        *,
        stale_after: timedelta = timedelta(minutes=30),
        max_attempts: int = 3,
        worker_id: str | None = None,
        retry_base_seconds: float = 0.0,
        retry_max_seconds: float = 900.0,
    ) -> None:
        """Create a queue view over ``session``.

        ``worker_id`` identifies the claiming process (C-02): ``claim_next``
        stores it, and ``complete``/``fail``/``requeue``/``skip_claimed``/
        ``heartbeat`` only change a job that is still RUNNING and claimed by it
        (no-op returning ``False`` otherwise). ``None`` keeps the unguarded
        behaviour for callers that never claim (API, tests).
        ``retry_base_seconds`` > 0 enables exponential backoff with jitter in
        ``requeue`` (C-05); ``0`` retries immediately.
        """

        self._session = session
        self._stale_after = stale_after
        self._max_attempts = max_attempts
        self._worker_id = worker_id
        self._retry_base_seconds = max(0.0, retry_base_seconds)
        self._retry_max_seconds = max(self._retry_base_seconds, retry_max_seconds)

    def enqueue(self, analysis_id: UUID) -> None:
        """Create a pending job idempotently for an analysis."""

        with span("queue.enqueue"):
            # Persist the caller's trace so a worker in another process can
            # continue it (``analysis_jobs.traceparent``; NULL when tracing is off).
            traceparent = current_traceparent()
            row = self._session.scalar(
                select(db_models.AnalysisJob).where(
                    db_models.AnalysisJob.analysis_id == analysis_id
                )
            )
            if row is None:
                self._session.add(
                    db_models.AnalysisJob(
                        analysis_id=analysis_id,
                        status=db_enums.AnalysisJobStatus.PENDING,
                        attempts=0,
                        traceparent=traceparent,
                    )
                )
            elif row.status == db_enums.AnalysisJobStatus.FAILED:
                # An explicit re-enqueue is a fresh run: without resetting the
                # attempt counter an exhausted job would sit pending forever,
                # because ``claim_next`` skips jobs at ``max_attempts``.
                row.status = db_enums.AnalysisJobStatus.PENDING
                row.attempts = 0
                row.last_error = None
                row.locked_at = None
                row.claimed_by = None
                row.available_at = None
                # A fresh run starts from the re-enqueuing caller's trace.
                row.traceparent = traceparent
            self._session.flush()

    def depth_by_status(self) -> dict[str, int]:
        """Return the number of jobs per status (for the queue-depth gauge)."""

        rows = self._session.execute(
            select(db_models.AnalysisJob.status, func.count()).group_by(
                db_models.AnalysisJob.status
            )
        ).all()
        return {str(getattr(status, "value", status)): count for status, count in rows}

    def claim_next(self) -> AnalysisJob | None:
        """Claim the next pending or stale running job."""

        self.recover_stale_jobs()
        now = datetime.now(UTC)
        query = (
            select(db_models.AnalysisJob)
            .where(
                db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.PENDING,
                db_models.AnalysisJob.attempts < self._max_attempts,
                or_(
                    db_models.AnalysisJob.available_at.is_(None),
                    db_models.AnalysisJob.available_at <= now,
                ),
            )
            .order_by(db_models.AnalysisJob.created_at)
            .limit(1)
        )
        bind = self._session.get_bind()
        if bind is not None and getattr(bind.dialect, "name", None) == "postgresql":
            query = query.with_for_update(skip_locked=True)

        row = self._session.scalar(query)
        if row is None:
            return None
        row.status = db_enums.AnalysisJobStatus.RUNNING
        row.attempts += 1
        row.locked_at = now
        row.claimed_by = self._worker_id
        row.available_at = None
        row.last_error = None
        self._session.flush()
        _log_transition(row, "claimed")
        return self._to_dto(row)

    def cancel_queued(self, analysis_id: UUID, reason: str) -> bool:
        """Cancel a job that has not started; never touch a claimed one.

        Returns ``True`` when nothing is left to run (the job was pending with
        zero attempts, or no job exists) and ``False`` when a worker already
        claimed it (running) or has attempted it (a retry whose in-progress
        check is already on GitHub; it is left to finish and complete that
        check). The state change is one conditional UPDATE, so it cannot race
        ``claim_next``. The cancelled job is stored as ``completed`` with
        ``last_error = "Cancelled: ..."`` (the ``analysisjobstatus`` enum has no
        cancelled member and adding one needs a Postgres enum migration).
        """

        if self._session.scalar(
            select(db_models.AnalysisJob.id).where(
                db_models.AnalysisJob.analysis_id == analysis_id
            )
        ) is None:
            return True
        result = self._session.execute(
            update(db_models.AnalysisJob)
            .where(
                db_models.AnalysisJob.analysis_id == analysis_id,
                db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.PENDING,
                db_models.AnalysisJob.attempts == 0,
            )
            .values(
                status=db_enums.AnalysisJobStatus.COMPLETED,
                last_error=_safe_error(f"{CANCELLED_PREFIX}{reason}"),
                locked_at=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        self._session.flush()
        cancelled = bool(result.rowcount)
        if cancelled:
            LOGGER.info(
                "Analysis job cancelled",
                extra={"analysis_id": str(analysis_id), "outcome": "cancelled"},
            )
        return cancelled

    def skip_claimed(self, analysis_id: UUID, reason: str) -> bool:
        """Finish a just-claimed job without running it (analysis no longer wanted).

        The analysis is cancelled unless it is already terminal; the job ends
        ``completed`` with ``last_error = "Cancelled: ..."``. Returns ``False``
        (and changes nothing) when this worker no longer holds the lease.
        """

        row = self._owned_job(analysis_id, "skip")
        if row is None:
            return False
        row.status = db_enums.AnalysisJobStatus.COMPLETED
        row.last_error = _safe_error(f"{CANCELLED_PREFIX}{reason}")
        row.locked_at = None
        analysis = self._session.get(db_models.Analysis, analysis_id)
        if analysis is not None and analysis.status not in _TERMINAL_ANALYSIS_STATUSES:
            analysis.status = db_enums.AnalysisStatus.CANCELLED
            analysis.completed_at = datetime.now(UTC)
        self._session.flush()
        _log_transition(row, "cancelled")
        return True

    def heartbeat(self, analysis_id: UUID) -> bool:
        """Renew the lease (``locked_at``) of a job this worker still holds (C-02).

        One conditional UPDATE, so it is safe from a background thread with its
        own session. Returns ``False`` when the lease is lost: the job was
        recovered as stale, finished, or claimed by another worker.
        """

        conditions = [
            db_models.AnalysisJob.analysis_id == analysis_id,
            db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.RUNNING,
        ]
        if self._worker_id is not None:
            conditions.append(db_models.AnalysisJob.claimed_by == self._worker_id)
        result = self._session.execute(
            update(db_models.AnalysisJob)
            .where(*conditions)
            .values(locked_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        self._session.flush()
        return bool(result.rowcount)

    def complete(self, analysis_id: UUID) -> bool:
        """Mark an analysis job completed (``False`` when the lease was lost)."""

        row = self._owned_job(analysis_id, "complete")
        if row is None:
            return False
        row.status = db_enums.AnalysisJobStatus.COMPLETED
        row.locked_at = None
        self._session.flush()
        _log_transition(row, "completed")
        return True

    def fail(self, analysis_id: UUID, error: str) -> bool:
        """Mark an analysis job failed. ``error`` is redacted before storage."""

        row = self._owned_job(analysis_id, "fail")
        if row is None:
            return False
        row.status = db_enums.AnalysisJobStatus.FAILED
        row.last_error = _safe_error(error)
        row.locked_at = None
        self._session.flush()
        _log_transition(row, "failed", logging.WARNING)
        return True

    def requeue(self, analysis_id: UUID, error: str) -> bool:
        """Return a failed attempt to pending for another try, after a backoff."""

        row = self._owned_job(analysis_id, "requeue")
        if row is None:
            return False
        if row.attempts >= self._max_attempts:
            row.status = db_enums.AnalysisJobStatus.FAILED
        else:
            row.status = db_enums.AnalysisJobStatus.PENDING
            row.available_at = self._next_available_at(row.attempts)
            # Waiting for the retry: the analysis is queued again, not running.
            analysis = self._session.get(db_models.Analysis, analysis_id)
            if analysis is not None and analysis.status == db_enums.AnalysisStatus.RUNNING:
                analysis.status = db_enums.AnalysisStatus.PENDING
        row.last_error = _safe_error(error)
        row.locked_at = None
        self._session.flush()
        _log_transition(
            row,
            "failed" if row.status == db_enums.AnalysisJobStatus.FAILED else "requeued",
            logging.WARNING,
        )
        return True

    def _next_available_at(self, attempts: int) -> datetime | None:
        """Exponential backoff (base * 2^(attempts-1), capped) with +-25% jitter."""

        if self._retry_base_seconds <= 0:
            return None
        delay = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** max(0, attempts - 1)),
        )
        delay *= random.uniform(0.75, 1.25)  # noqa: S311 - jitter, not security
        return datetime.now(UTC) + timedelta(seconds=delay)

    def _owned_job(self, analysis_id: UUID, action: str) -> db_models.AnalysisJob | None:
        """Return the job for a state change, or ``None`` when the lease is lost.

        With a ``worker_id`` the row is re-read from the database (never the
        session cache) and must be RUNNING and claimed by this worker; the row
        is locked on PostgreSQL. Without one the legacy unguarded lookup applies.
        """

        if self._worker_id is None:
            return self._require_job(analysis_id)
        query = (
            select(db_models.AnalysisJob)
            .where(db_models.AnalysisJob.analysis_id == analysis_id)
            .execution_options(populate_existing=True)
        )
        bind = self._session.get_bind()
        if bind is not None and getattr(bind.dialect, "name", None) == "postgresql":
            query = query.with_for_update()
        row = self._session.scalar(query)
        if row is None:
            msg = f"Analysis job for {analysis_id} was not found."
            raise KeyError(msg)
        if (
            row.status != db_enums.AnalysisJobStatus.RUNNING
            or row.claimed_by != self._worker_id
        ):
            LOGGER.warning(
                "Analysis job lease lost; %s ignored",
                action,
                extra={
                    "analysis_id": str(analysis_id),
                    "job_id": str(row.id),
                    "outcome": "lease_lost",
                },
            )
            return None
        return row

    def mark_analysis_failed(self, analysis_id: UUID) -> bool:
        """Move a non-terminal analysis row to ``failed``.

        The worker's pipeline session is rolled back when it raises, so the
        orchestrator's own ``fail_analysis`` never persists; this records the
        terminal state from the failure-handling session instead. Returns
        whether the row changed (completed/cancelled/failed rows are kept).
        """

        analysis = self._session.get(db_models.Analysis, analysis_id)
        if analysis is None or analysis.status in _TERMINAL_ANALYSIS_STATUSES:
            return False
        analysis.status = db_enums.AnalysisStatus.FAILED
        analysis.completed_at = datetime.now(UTC)
        self._session.flush()
        LOGGER.warning(
            "Analysis marked failed",
            extra={"analysis_id": str(analysis_id), "outcome": "analysis_failed"},
        )
        return True

    def reap_stuck_analyses(
        self,
        *,
        deadline: timedelta,
        now: datetime | None = None,
    ) -> list[ReapedAnalysis]:
        """Fail analyses that can no longer finish, so none stays active forever.

        * Stale running jobs are recovered first (requeued, or failed when
          their attempts are exhausted).
        * A pending/running analysis whose job has ``failed`` is failed.
        * An analysis whose job holds a live lease (``status = running``, ``claimed_by`` set and
          ``locked_at`` renewed within the stale window) is NEVER reaped for taking long: the
          heartbeat proves a worker is still on it (C-18). A job that stops heartbeating is
          recovered by ``recover_stale_jobs`` above, whatever the deadline.
        * Any other pending/running analysis is failed once ``deadline`` has passed since the
          job last changed (queued, claimed, requeued; ``analysis.started_at`` when it has
          no job), and its job (unless completed) is failed too, so a worker that is still
          holding it cannot retry it.
        """

        self.recover_stale_jobs()
        current = now or datetime.now(UTC)
        cutoff = current - deadline
        lease_cutoff = current - self._stale_after
        rows = self._session.execute(
            select(db_models.Analysis, db_models.AnalysisJob)
            .outerjoin(
                db_models.AnalysisJob,
                db_models.AnalysisJob.analysis_id == db_models.Analysis.id,
            )
            .where(db_models.Analysis.status.in_(_ACTIVE_ANALYSIS_STATUSES))
        ).all()
        reaped: list[ReapedAnalysis] = []
        for analysis, job in rows:
            if job is not None and job.status == db_enums.AnalysisJobStatus.FAILED:
                reason = job.last_error or EXHAUSTED_ATTEMPTS_ERROR
            elif _lease_is_live(job, lease_cutoff):
                continue  # C-18: a heartbeating worker is on it; length alone never reaps it
            elif _deadline_reference(analysis, job) < _as_utc(cutoff):
                reason = (
                    "Analysis did not finish within "
                    f"{int(deadline.total_seconds())}s and was stopped."
                )
                if job is not None and job.status != db_enums.AnalysisJobStatus.COMPLETED:
                    job.status = db_enums.AnalysisJobStatus.FAILED
                    job.last_error = reason
                    job.locked_at = None
            else:
                continue
            analysis.status = db_enums.AnalysisStatus.FAILED
            analysis.completed_at = current
            reaped.append(
                ReapedAnalysis(
                    analysis_id=analysis.id,
                    job_id=job.id if job is not None else None,
                    reason=_safe_error(reason),
                )
            )
            LOGGER.warning(
                "Reaped stuck analysis",
                extra={
                    "analysis_id": str(analysis.id),
                    "job_id": str(job.id) if job is not None else None,
                    "attempt": job.attempts if job is not None else None,
                    "outcome": "reaped",
                    "reason": _safe_error(reason),
                },
            )
        self._session.flush()
        return reaped

    def recover_stale_jobs(self) -> int:
        """Return stale running jobs back to pending (or fail exhausted ones)."""

        cutoff = datetime.now(UTC) - self._stale_after
        rows = self._session.scalars(
            select(db_models.AnalysisJob).where(
                db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.RUNNING,
                db_models.AnalysisJob.locked_at < cutoff,
            )
        ).all()
        for row in rows:
            row.locked_at = None
            row.claimed_by = None
            if row.attempts >= self._max_attempts:
                row.status = db_enums.AnalysisJobStatus.FAILED
                row.last_error = EXHAUSTED_ATTEMPTS_ERROR
                outcome = "stale_failed"
            else:
                row.status = db_enums.AnalysisJobStatus.PENDING
                row.last_error = "Recovered stale running job."
                outcome = "stale_requeued"
            _log_transition(row, outcome, logging.WARNING)
        self._session.flush()
        return len(rows)

    def get_by_analysis_id(self, analysis_id: UUID) -> AnalysisJob | None:
        """Return job state for an analysis."""

        row = self._session.scalar(
            select(db_models.AnalysisJob).where(
                db_models.AnalysisJob.analysis_id == analysis_id
            )
        )
        return self._to_dto(row) if row is not None else None

    def _require_job(self, analysis_id: UUID) -> db_models.AnalysisJob:
        row = self._session.scalar(
            select(db_models.AnalysisJob).where(
                db_models.AnalysisJob.analysis_id == analysis_id
            )
        )
        if row is None:
            msg = f"Analysis job for {analysis_id} was not found."
            raise KeyError(msg)
        return row

    @staticmethod
    def _to_dto(row: db_models.AnalysisJob) -> AnalysisJob:
        return AnalysisJob(
            id=row.id,
            analysis_id=row.analysis_id,
            status=row.status.value,
            attempts=row.attempts,
            last_error=row.last_error,
            locked_at=row.locked_at,
            traceparent=row.traceparent,
            claimed_by=row.claimed_by,
            available_at=row.available_at,
        )


def _safe_error(error: object) -> str:
    return redact_secrets(error, max_length=MAX_ERROR_LENGTH)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC for comparisons."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _log_transition(
    row: db_models.AnalysisJob,
    outcome: str,
    level: int = logging.INFO,
) -> None:
    extra = {
        "analysis_id": str(row.analysis_id),
        "job_id": str(row.id),
        "attempt": row.attempts,
        "outcome": outcome,
    }
    if row.last_error and outcome not in {"claimed", "completed"}:
        extra["error"] = row.last_error  # already redacted on write
    LOGGER.log(level, "Analysis job %s", outcome, extra=extra)
