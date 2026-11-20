"""AI merge-readiness review persistence (DEC-041).

``analysis_ai_reviews`` holds at most one row per analysis: the validated, advisory
AI review (JSON) or the reason it is unavailable. It is written after the analysis
result is committed and is never read by verdict, score or check-run logic.
Tenant-scoped by ``organization_id`` like every newer table.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radius_shared.database.base import Base, UuidPrimaryKeyMixin


class AnalysisAiReviewRow(UuidPrimaryKeyMixin, Base):
    """The advisory AI review of one analysis (status ``ok`` or ``unavailable``)."""

    __tablename__ = "analysis_ai_reviews"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("analysis_id", name="uq_analysis_ai_reviews_analysis_id"),
        Index("ix_analysis_ai_reviews_organization_id", "organization_id"),
    )
