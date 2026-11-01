"""SQLAlchemy-backed durable analysis job queue."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.redaction import redact_secrets
from sqlalchemy import select
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


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    """Durable analysis job DTO."""

    id: UUID
    analysis_id: UUID
    status: str
    attempts: int
    last_error: str | None
    locked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReapedAnalysis:
    """An analysis the reaper moved to ``failed`` because it could not finish."""

    analysis_id: UUID
    job_id: UUID | None
    reason: str


class SqlAlchemyAnalysisJobQueue:
    """Durable FIFO queue for analysis execution."""

    def __init__(
        self,
        session: Session,
        *,
        stale_after: timedelta = timedelta(minutes=30),
        max_attempts: int = 3,
    ) -> None:
        self._session = session
        self._stale_after = stale_after
        self._max_attempts = max_attempts

    def enqueue(self, analysis_id: UUID) -> None:
        """Create a pending job idempotently for an analysis."""

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
        self._session.flush()

    def claim_next(self) -> AnalysisJob | None:
        """Claim the next pending or stale running job."""

        self.recover_stale_jobs()
        query = (
            select(db_models.AnalysisJob)
            .where(
                db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.PENDING,
                db_models.AnalysisJob.attempts < self._max_attempts,
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
        row.locked_at = datetime.now(UTC)
        row.last_error = None
        self._session.flush()
        _log_transition(row, "claimed")
        return self._to_dto(row)

    def complete(self, analysis_id: UUID) -> None:
        """Mark an analysis job completed."""

        row = self._require_job(analysis_id)
        row.status = db_enums.AnalysisJobStatus.COMPLETED
        row.locked_at = None
        self._session.flush()
        _log_transition(row, "completed")

    def fail(self, analysis_id: UUID, error: str) -> None:
        """Mark an analysis job failed. ``error`` is redacted before storage."""

        row = self._require_job(analysis_id)
        row.status = db_enums.AnalysisJobStatus.FAILED
        row.last_error = _safe_error(error)
        row.locked_at = None
        self._session.flush()
        _log_transition(row, "failed", logging.WARNING)

    def requeue(self, analysis_id: UUID, error: str) -> None:
        """Return a failed attempt to pending for another try."""

        row = self._require_job(analysis_id)
        if row.attempts >= self._max_attempts:
            row.status = db_enums.AnalysisJobStatus.FAILED
        else:
            row.status = db_enums.AnalysisJobStatus.PENDING
        row.last_error = _safe_error(error)
        row.locked_at = None
        self._session.flush()
        _log_transition(
            row,
            "failed" if row.status == db_enums.AnalysisJobStatus.FAILED else "requeued",
            logging.WARNING,
        )

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
        * A pending/running analysis started more than ``deadline`` ago is
          failed, and its job (unless completed) is failed too, so a worker
          that is still holding it cannot retry it.
        """

        self.recover_stale_jobs()
        current = now or datetime.now(UTC)
        cutoff = current - deadline
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
            elif _as_utc(analysis.started_at) < _as_utc(cutoff):
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
