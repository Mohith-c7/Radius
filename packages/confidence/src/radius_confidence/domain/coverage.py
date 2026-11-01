"""Coverage domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union
from uuid import UUID

from radius_confidence.domain.value_objects import CoveragePercent

Self = Union[object, "CoverageFile"]


@dataclass(frozen=True)
class CoverageFile:
    """A source file covered by one or more tests."""

    id: UUID | None
    coverage_report_id: UUID
    path: str
    source_language: str = "unknown"
    covered_lines: int = 0
    total_lines: int = 0
    covered_percent: CoveragePercent | None = None

    def __post_init__(self) -> None:
        if self.total_lines < 0:
            msg = "Total lines cannot be negative."
            raise ValueError(msg)
        if self.covered_lines < 0 or self.covered_lines > self.total_lines:
            msg = "Covered lines cannot exceed total lines."
            raise ValueError(msg)
        if self.covered_percent is not None and self.covered_percent.value > 100:
            msg = "Coverage percent cannot exceed 100."
            raise ValueError(msg)

    @classmethod
    def from_artifact(
        cls,
        coverage_report_id: UUID,
        path: str,
        source_language: str,
        covered_lines: int,
        total_lines: int,
    ) -> Self:
        return cls(
            id=None,
            coverage_report_id=coverage_report_id,
            path=path,
            source_language=source_language,
            covered_lines=covered_lines,
            total_lines=total_lines,
            covered_percent=(
                CoveragePercent(covered_lines * 100 / total_lines)
                if total_lines
                else None
            ),
        )


@dataclass(frozen=True)
class CoverageSymbol:
    """A function/symbol executed by a test."""

    id: UUID | None
    coverage_report_id: UUID
    file_path: str
    symbol: str
    test_id: UUID
    executed: bool = False
    count: int = 0

    def __post_init__(self) -> None:
        if self.count < 0:
            msg = "Execution count cannot be negative."
            raise ValueError(msg)

    @classmethod
    def from_artifact(
        cls,
        coverage_report_id: UUID,
        file_path: str,
        symbol: str,
        test_id: UUID,
        executed: bool,
        count: int,
    ) -> Self:
        return cls(
            id=None,
            coverage_report_id=coverage_report_id,
            file_path=file_path,
            symbol=symbol,
            test_id=test_id,
            executed=executed,
            count=count,
        )


@dataclass(frozen=True)
class CoverageReportValueObject:
    """Snapshot of coverage metrics for an analysis."""

    covered_lines: int
    total_lines: int
    coverage_percent: CoveragePercent | None
    artifacts: int

    def __post_init__(self) -> None:
        if self.covered_lines < 0 or self.total_lines < 0:
            msg = "Lines cannot be negative."
            raise ValueError(msg)
        if self.covered_lines > self.total_lines:
            msg = "Covered lines cannot exceed total lines."
            raise ValueError(msg)

    @property
    def is_available(self) -> bool:
        return self.total_lines > 0 and self.coverage_percent is not None
