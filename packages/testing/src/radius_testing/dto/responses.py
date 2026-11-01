"""Testing response DTOs."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from radius_testing.domain.entities import (
    SelectedTest,
    TestCase,
    TestRunPlan,
    TestRunResult,
    TestSelection,
    TestSelectionDecision,
)


@dataclass(frozen=True, slots=True)
class TestCaseResponse:
    """Test case response DTO."""

    id: UUID
    name: str
    path: str
    framework: str
    test_type: str
    target_path: str | None

    @classmethod
    def from_entity(cls, test_case: TestCase) -> "TestCaseResponse":
        """Create a response DTO from a test case."""

        return cls(
            id=test_case.id,
            name=test_case.name.value,
            path=test_case.path.value,
            framework=test_case.framework.value,
            test_type=test_case.test_type.value,
            target_path=(
                test_case.target_path.value if test_case.target_path else None
            ),
        )


@dataclass(frozen=True, slots=True)
class TestDiscoveryResponse:
    """Test discovery response DTO."""

    test_count: int
    tests: tuple[TestCaseResponse, ...]


@dataclass(frozen=True, slots=True)
class SelectedTestResponse:
    """Selected test response DTO."""

    test: TestCaseResponse
    reason: str

    @classmethod
    def from_entity(cls, selected: SelectedTest) -> "SelectedTestResponse":
        """Create a response DTO from a selected test."""

        return cls(
            test=TestCaseResponse.from_entity(selected.test_case),
            reason=selected.reason.value,
        )


@dataclass(frozen=True, slots=True)
class TestDecisionResponse:
    """One selected or skipped test with its concrete evidence."""

    test: TestCaseResponse
    decision: str
    evidence_sources: tuple[str, ...]
    evidence_details: tuple[str, ...]
    relevance_score: float
    reason: str

    @classmethod
    def from_entity(cls, item: TestSelectionDecision) -> "TestDecisionResponse":
        return cls(
            test=TestCaseResponse.from_entity(item.test_case), decision=item.decision.value,
            evidence_sources=item.evidence_sources, evidence_details=item.evidence_details,
            relevance_score=item.relevance_score, reason=item.reason,
        )


@dataclass(frozen=True, slots=True)
class TestSelectionResponse:
    """Test selection response DTO."""

    analysis_id: UUID
    selected_count: int
    skipped_count: int
    total_count: int
    time_saved_percent: float
    cli_args: str
    selected_tests: tuple[SelectedTestResponse, ...]
    skipped_tests: tuple[TestCaseResponse, ...]
    created_at: datetime
    decisions: tuple[TestDecisionResponse, ...] = ()

    @classmethod
    def from_entity(cls, selection: TestSelection) -> "TestSelectionResponse":
        """Create a response DTO from a test selection."""

        return cls(
            analysis_id=selection.analysis_id,
            selected_count=selection.selected_count,
            skipped_count=selection.skipped_count,
            total_count=selection.total_discovered_count,
            time_saved_percent=selection.time_saved_percent,
            cli_args=selection.cli_args,
            selected_tests=tuple(
                SelectedTestResponse.from_entity(item)
                for item in selection.selected_tests
            ),
            decisions=tuple(TestDecisionResponse.from_entity(item) for item in selection.decisions),
            skipped_tests=tuple(
                TestCaseResponse.from_entity(t)
                for t in selection.skipped_tests
            ),
            created_at=selection.created_at,
        )


@dataclass(frozen=True, slots=True)
class TestRunPlanResponse:
    """Structured test run plan response DTO."""

    id: UUID
    analysis_id: UUID
    status: str
    selected_count: int
    command_plan: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def from_entity(cls, plan: TestRunPlan) -> "TestRunPlanResponse":
        """Create a response DTO from a run plan."""

        return cls(
            id=plan.id,
            analysis_id=plan.analysis_id,
            status=plan.status.value,
            selected_count=len(plan.selected_tests),
            command_plan=plan.command_plan,
        )


@dataclass(frozen=True, slots=True)
class TestRunResultResponse:
    """Executed test run summary response."""

    id: UUID
    analysis_id: UUID
    status: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int
    coverage_percent: float | None
    output: str

    @classmethod
    def from_entity(cls, result: TestRunResult) -> "TestRunResultResponse":
        """Create a response DTO from a test run result."""

        return cls(
            id=result.id,
            analysis_id=result.analysis_id,
            status=result.status.value,
            total_tests=result.total_tests,
            passed=result.passed,
            failed=result.failed,
            skipped=result.skipped,
            duration_ms=result.duration_ms,
            coverage_percent=result.coverage_percent,
            output=result.output,
        )


@dataclass(frozen=True, slots=True)
class TestUploadResponse:
    """The single report accepted (or recognised as a replay) by one upload."""

    id: UUID
    commit_sha: str
    body_sha256: str
    duplicate: bool
    status: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    reported_cases: int


@dataclass(frozen=True, slots=True)
class SelectedTestAttributionResponse:
    """Selected test files split by what the accumulated results show.

    ``executed`` = ``passed`` + ``failed``. Being in the plan never counts as
    executed: ``skipped`` files had only skipped cases and ``not_reported``
    files had none.
    """

    selected_count: int
    executed_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    not_reported_count: int
    executed: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]
    not_reported: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestIngestionResponse:
    """Result of one CI upload, with counts aggregated over every upload.

    Top-level counts are the aggregate the verdict is computed from (all
    distinct uploads for the analysis); ``upload`` describes this request.
    """

    id: UUID
    analysis_id: UUID
    status: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int
    coverage_percent: float | None
    output: str
    upload_count: int
    upload: TestUploadResponse
    selected_tests: SelectedTestAttributionResponse | None
    contradictory_cases: tuple[str, ...] = ()
    verification_status: str | None = None
