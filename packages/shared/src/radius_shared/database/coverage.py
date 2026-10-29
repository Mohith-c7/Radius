"""SQLAlchemy persistence models for normalized runtime coverage."""

from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radius_shared.database.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class CoverageReport(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Coverage snapshot attached to one analysis."""
    __tablename__ = "coverage_reports"
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), unique=True, nullable=False, index=True)
    framework: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    covered_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage_percent: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    artifact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    associations: Mapped[list["CoverageReportTestAssociation"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    artifacts: Mapped[list["CoverageArtifact"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class CoverageReportTestAssociation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A test that generated coverage in a report."""
    __tablename__ = "coverage_report_test_association"
    report_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_reports.id"), nullable=False, index=True)
    test_id: Mapped[UUID] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report: Mapped[CoverageReport] = relationship(back_populates="associations")
    test_case = relationship("TestCase")
    __table_args__ = (UniqueConstraint("report_id", "test_id", name="uq_coverage_report_test"),)


class CoverageArtifact(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """One observed test-to-file or test-to-symbol execution relationship."""
    __tablename__ = "coverage_artifacts"
    report_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_reports.id"), nullable=False, index=True)
    test_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_report_test_association.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    covered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    report: Mapped[CoverageReport] = relationship(back_populates="artifacts")
    __table_args__ = (UniqueConstraint("test_id", "path", "symbol", name="uq_coverage_lines"),)
