"""Database model for flaky test classification.

This model stores the classification status for a test case, along with statistics
used to determine the status.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from radius_shared.database.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from radius_shared.database.enums import StrEnum
from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from radius_shared.database.models import TestCase


class FlakyStatus(StrEnum):
    STABLE = "stable"
    POTENTIALLY_FLAKY = "potentially_flaky"
    FAILING = "failing"
    INSUFFICIENT_DATA = "insufficient_data"


class FlakyClassification(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted classification of a test's flakiness.

    Fields:
        test_case_id: FK to the TestCase this classification belongs to.
        status: One of the FlakyStatus enum values.
        reason: Human‑readable explanation of the classification.
        total_runs: Number of recent executions considered.
        fail_runs: Number of those executions that failed.
        score: Failure proportion (0.0‑1.0).
        updated_at: Timestamp of the latest classification update.
    """

    __tablename__ = "flaky_classification"

    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[FlakyStatus] = mapped_column(
        Enum(FlakyStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    test_case: Mapped[TestCase] = relationship(
        "TestCase",
        foreign_keys=[test_case_id],
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint("test_case_id", name="uq_flaky_classification_test_case"),
        Index("ix_flaky_classification_status", "status"),
    )
