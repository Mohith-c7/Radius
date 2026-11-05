"""Testing domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from radius_testing.domain.enums import (
    TestDecision,
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
class TestSelectionDecision:
    """Auditable decision backed exclusively by Radius evidence."""

    test_case: TestCase
    decision: TestDecision
    evidence_sources: tuple[str, ...]
    evidence_details: tuple[str, ...]
    relevance_score: float
    reason: str


@dataclass(frozen=True, slots=True)
class TestSelection:
    """Selected tests for one analysis."""

    analysis_id: UUID
    selected_tests: tuple[SelectedTest, ...]
    decisions: tuple[TestSelectionDecision, ...] = ()
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
    flaky: int = 0
    """Cases that failed then passed on rerun (F-11). Not in ``passed`` or ``failed``."""
    flaky_tests: tuple[str, ...] = ()
    """Identities (``file::name``) of the flaky cases, sorted."""


class CaseOutcome:
    """Outcome of one reported test case."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ReportedTestCase:
    """Identity, location hints and outcome of one test case in a CI report."""

    file: str | None = None
    classname: str | None = None
    name: str | None = None
    outcome: str = CaseOutcome.PASSED

    @property
    def executed(self) -> bool:
        """Return whether the case actually ran (passed or failed)."""

        return self.outcome != CaseOutcome.SKIPPED

    @property
    def key(self) -> tuple[str, str, str]:
        """Return a stable identity used to merge the same case across uploads."""

        file = (self.file or "").replace("\\", "/").strip()
        while file.startswith("./"):
            file = file[2:]
        return (file, (self.classname or "").strip(), (self.name or "").strip())


@dataclass(frozen=True, slots=True)
class TestResultUpload:
    """One CI test report uploaded for an analysis, bound to a commit.

    Uploads accumulate: a later upload never replaces an earlier one, so a
    passing shard (or replay) cannot erase a failing one.
    """

    id: UUID
    analysis_id: UUID
    commit_sha: str
    body_sha256: str
    result: TestRunResult
    cases: tuple[ReportedTestCase, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
