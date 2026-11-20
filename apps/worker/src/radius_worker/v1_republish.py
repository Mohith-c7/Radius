"""Republish the v1 Check Run and PR comment after CI uploads test results.

``POST /analyses/{id}/tests/results`` re-scores the v1 confidence report in the
database, but the API holds no GitHub credentials, and the Verdict v2 outbox
only runs with ``RADIUS_FEATURE_VERDICT_V2`` on. With v2 ``off`` or ``shadow``
(the production default) the GitHub check therefore kept saying "awaiting CI"
after CI had uploaded passing or failing results.

This sweep runs in the worker loop: every ``interval_seconds`` it looks for
analyses whose newest upload (last ``max_age``) has not been published yet by
this process and republishes the stored v1 report. Publishing is idempotent
(the existing check run and Radius comment are updated in place), so a worker
restart costs at most one repeat publication per recent analysis. It never
publishes:

* when v2 is ``on`` (the v2 outbox republishes then);
* an analysis that is no longer the newest of its pull request (the PR comment
  belongs to the newest head);
* a report older than the upload (the re-score has not been committed yet).

Errors are logged and retried on the next pass, at most ``max_attempts`` times
per upload; the sweep never raises.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from radius_shared.database import models as db_models
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_flag import VerdictV2Mode
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

LOGGER = logging.getLogger(__name__)

PublishFn = Callable[[Session, UUID], None]
"""Publish the stored v1 report of one analysis; raises on failure."""

_MEMORY_LIMIT = 2048


@dataclass(slots=True)
class V1CiRepublisher:
    """Bounded, idempotent v1 republish after CI results (see module docstring)."""

    session_factory: sessionmaker[Session]
    publish: PublishFn
    verdict_v2_mode: VerdictV2Mode = VerdictV2Mode.OFF
    enabled: bool = True
    interval_seconds: float = 30.0
    max_age: timedelta = timedelta(days=2)
    limit: int = 20
    max_attempts: int = 5
    _published: OrderedDict[UUID, datetime] = field(default_factory=OrderedDict)
    _failures: dict[tuple[UUID, datetime], int] = field(default_factory=dict)
    _next_run: float = 0.0

    def tick(self, *, now: datetime | None = None, force: bool = False) -> int:
        """Run one pass when due; return how many analyses were republished."""

        if not self.enabled or self.verdict_v2_mode == VerdictV2Mode.ON:
            return 0
        if not force and time.monotonic() < self._next_run:
            return 0
        self._next_run = time.monotonic() + self.interval_seconds
        try:
            return self._sweep(now or datetime.now(UTC))
        except Exception as exc:
            LOGGER.warning(
                "v1 republish sweep failed; continuing",
                extra={"outcome": "v1_republish_error", "error": redact_secrets(exc)},
            )
            return 0

    def _sweep(self, now: datetime) -> int:
        with self.session_factory() as session:
            candidates = self._candidates(session, now)
        published = 0
        for analysis_id, last_upload in candidates:
            if published >= self.limit:
                break
            if self._published.get(analysis_id) == last_upload:
                continue
            key = (analysis_id, last_upload)
            if self._failures.get(key, 0) >= self.max_attempts:
                continue
            try:
                with self.session_factory() as session:
                    reason = _skip_reason(session, analysis_id, last_upload)
                    if reason == "report_not_rescored":
                        continue  # retry next pass; do not remember this upload
                    if reason is None:
                        self.publish(session, analysis_id)
                        published += 1
                    session.rollback()
            except Exception as exc:
                self._failures[key] = self._failures.get(key, 0) + 1
                LOGGER.warning(
                    "Could not republish v1 result after CI upload: %s",
                    redact_secrets(exc),
                    extra={
                        "analysis_id": str(analysis_id),
                        "attempt": self._failures[key],
                        "outcome": "v1_republish_error",
                    },
                )
                continue
            self._remember(analysis_id, last_upload)
            if reason is None:
                LOGGER.info(
                    "Republished v1 result after CI upload",
                    extra={"analysis_id": str(analysis_id), "outcome": "v1_republished"},
                )
        return published

    def _candidates(self, session: Session, now: datetime) -> list[tuple[UUID, datetime]]:
        last_upload = func.max(db_models.TestResultUpload.created_at)
        rows = session.execute(
            select(db_models.TestResultUpload.analysis_id, last_upload)
            .where(db_models.TestResultUpload.created_at >= now - self.max_age)
            .group_by(db_models.TestResultUpload.analysis_id)
            .order_by(last_upload.desc())
            .limit(self.limit * 5)
        ).all()
        return [(row[0], _aware(row[1])) for row in rows]

    def _remember(self, analysis_id: UUID, last_upload: datetime) -> None:
        self._published[analysis_id] = last_upload
        self._published.move_to_end(analysis_id)
        while len(self._published) > _MEMORY_LIMIT:
            self._published.popitem(last=False)
        self._failures = {
            key: count for key, count in self._failures.items() if key[0] != analysis_id
        }


def _skip_reason(session: Session, analysis_id: UUID, last_upload: datetime) -> str | None:
    analysis = session.get(db_models.Analysis, analysis_id)
    if analysis is None or analysis.pull_request_id is None:
        return "no_pull_request"
    report = session.scalar(
        select(db_models.ConfidenceReport).where(
            db_models.ConfidenceReport.analysis_id == analysis_id
        )
    )
    if report is None:
        return "no_report"
    if _aware(report.generated_at) < last_upload:
        return "report_not_rescored"
    newest = session.scalar(
        select(db_models.Analysis.id)
        .where(db_models.Analysis.pull_request_id == analysis.pull_request_id)
        .order_by(db_models.Analysis.created_at.desc())
        .limit(1)
    )
    if newest is not None and newest != analysis_id:
        return "superseded"
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
