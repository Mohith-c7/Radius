"""Service for detecting flaky tests based on execution history.

The service reads recent TestExecutionHistory records for a given test case,
computes the failure rate, and stores a FlakyClassification record.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime

from radius_shared.database.models import TestCase, TestExecutionHistory
from radius_shared.database.session import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from sqlalchemy.orm import Session

from radius_testing.domain.models.flaky_classification import (
    FlakyClassification,
    FlakyStatus,
)


class FlakyDetectionService:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        # Configuration via environment variables with defaults
        self.min_runs = int(os.getenv("FLAKY_MIN_RUNS", "5"))
        self.threshold = float(os.getenv("FLAKY_THRESHOLD", "0.30"))
        if session_factory is not None:
            self.session_factory = session_factory
        else:
            self.session_factory = create_session_factory(create_database_engine(DatabaseSettings()))

    def _fetch_recent_histories(self, test_case_id) -> list[TestExecutionHistory]:
        with self.session_factory() as session:
            test_case = session.get(TestCase, test_case_id)
            if test_case is None:
                return []
            query = session.query(TestExecutionHistory).filter(
                TestExecutionHistory.test_path == test_case.path
            )
            if test_case.repository_id is not None:
                query = query.filter(
                    TestExecutionHistory.repository_id == test_case.repository_id
                )
            return (
                query.order_by(TestExecutionHistory.timestamp.desc())
                .limit(self.min_runs)
                .all()
            )

    def classify(self, test_case_id) -> FlakyClassification:
        histories = self._fetch_recent_histories(test_case_id)
        total = len(histories)
        fail = sum(1 for h in histories if h.status.lower() == "failed")
        # Determine status
        if total < self.min_runs:
            status = FlakyStatus.INSUFFICIENT_DATA
            reason = f"Only {total} runs available (minimum {self.min_runs})"
        elif fail == 0:
            status = FlakyStatus.STABLE
            reason = "All recent runs passed"
        elif fail == total:
            status = FlakyStatus.FAILING
            reason = "All recent runs failed"
        else:
            failure_rate = fail / total
            if failure_rate >= self.threshold:
                status = FlakyStatus.POTENTIALLY_FLAKY
                reason = f"Failure rate {failure_rate:.2%} exceeds threshold {self.threshold:.2%}"
            else:
                status = FlakyStatus.STABLE
                reason = f"Failure rate {failure_rate:.2%} below threshold"
        # Persist classification
        with self.session_factory() as session:
            classification = (
                session.query(FlakyClassification)
                .filter(FlakyClassification.test_case_id == test_case_id)
                .one_or_none()
            )
            if classification is None:
                classification = FlakyClassification(
                    test_case_id=test_case_id,
                    status=status,
                    reason=reason,
                    total_runs=total,
                    fail_runs=fail,
                    score=fail / total if total else 0,
                )
                session.add(classification)
            else:
                classification.status = status
                classification.reason = reason
                classification.total_runs = total
                classification.fail_runs = fail
                classification.score = fail / total if total else 0
                classification.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(classification)
            return classification
