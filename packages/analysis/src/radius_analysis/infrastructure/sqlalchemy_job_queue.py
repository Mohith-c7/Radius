"""SQLAlchemy-backed durable analysis job queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    """Durable analysis job DTO."""

    id: UUID
    analysis_id: UUID
    status: str
    attempts: int
    last_error: str | None
    locked_at: datetime | None


class SqlAlchemyAnalysisJobQueue:
    """Durable FIFO queue for analysis execution."""

    def __init__(
        self,
        session: Session,
        *,
        stale_after: timedelta = timedelta(minutes=30),
    ) -> None:
        self._session = session
        self._stale_after = stale_after

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
            row.status = db_enums.AnalysisJobStatus.PENDING
            row.last_error = None
            row.locked_at = None
        self._session.flush()

    def claim_next(self) -> AnalysisJob | None:
        """Claim the next pending or stale running job."""

        self.recover_stale_jobs()
        row = self._session.scalar(
            select(db_models.AnalysisJob)
            .where(db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.PENDING)
            .order_by(db_models.AnalysisJob.created_at)
            .limit(1)
        )
        if row is None:
            return None
        row.status = db_enums.AnalysisJobStatus.RUNNING
        row.attempts += 1
        row.locked_at = datetime.now(UTC)
        row.last_error = None
        self._session.flush()
        return self._to_dto(row)

    def complete(self, analysis_id: UUID) -> None:
        """Mark an analysis job completed."""

        row = self._require_job(analysis_id)
        row.status = db_enums.AnalysisJobStatus.COMPLETED
        row.locked_at = None
        self._session.flush()

    def fail(self, analysis_id: UUID, error: str) -> None:
        """Mark an analysis job failed."""

        row = self._require_job(analysis_id)
        row.status = db_enums.AnalysisJobStatus.FAILED
        row.last_error = error
        row.locked_at = None
        self._session.flush()

    def recover_stale_jobs(self) -> int:
        """Return stale running jobs back to pending."""

        cutoff = datetime.now(UTC) - self._stale_after
        rows = self._session.scalars(
            select(db_models.AnalysisJob).where(
                db_models.AnalysisJob.status == db_enums.AnalysisJobStatus.RUNNING,
                db_models.AnalysisJob.locked_at < cutoff,
            )
        ).all()
        for row in rows:
            row.status = db_enums.AnalysisJobStatus.PENDING
            row.locked_at = None
            row.last_error = "Recovered stale running job."
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
