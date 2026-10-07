"""Testing domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from radius_testing.domain.enums import (
    TestFramework,
    TestRunStatus,
    TestSelectionReason,
    TestType,
)
from radius_testing.domain.value_objects import SourcePath, TestName, TestPath


@dataclass(frozen=True, slots=True)
class TestCase:
    """One discoverable test file/case."""

    id: UUID
    name: TestName
    path: TestPath
    framework: TestFramework
    test_type: TestType = TestType.UNKNOWN
    target_path: SourcePath | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SelectedTest:
    """A selected test and its selection reason."""

    test_case: TestCase
    reason: TestSelectionReason


@dataclass(frozen=True, slots=True)
class TestSelection:
    """Selected tests for one analysis."""

    analysis_id: UUID
    selected_tests: tuple[SelectedTest, ...]
    skipped_tests: tuple[TestCase, ...] = ()
    total_discovered_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def selected_count(self) -> int:
        return len(self.selected_tests)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_tests)

    @property
    def time_saved_percent(self) -> float:
        if not self.total_discovered_count:
            return 0.0
        return round((self.skipped_count / self.total_discovered_count) * 100, 1)

    @property
    def cli_args(self) -> str:
        return " ".join(item.test_case.path.value for item in self.selected_tests)


@dataclass(frozen=True, slots=True)
class TestRunPlan:
    """Structured test run plan without executing commands."""

    id: UUID
    analysis_id: UUID
    status: TestRunStatus
    selected_tests: tuple[TestCase, ...]
    command_plan: tuple[tuple[str, tuple[str, ...]], ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def pending(
        cls,
        analysis_id: UUID,
        selected_tests: tuple[TestCase, ...],
        command_plan: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> "TestRunPlan":
        """Create a pending test run plan."""

        return cls(
            id=uuid4(),
            analysis_id=analysis_id,
            status=TestRunStatus.PENDING,
            selected_tests=selected_tests,
            command_plan=command_plan,
        )


@dataclass(frozen=True, slots=True)
class TestRunResult:
    """Executed test run summary."""

    id: UUID
    analysis_id: UUID
    status: TestRunStatus
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int
    coverage_percent: float | None = None
    output: str = ""
