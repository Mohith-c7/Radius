import hashlib
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from radius_shared.errors import NotFoundError, ValidationError

from radius_testing.domain.entities import (
    CaseOutcome,
    ReportedTestCase,
    TestResultUpload,
    TestRunResult,
)
from radius_testing.domain.enums import TestRunStatus
from radius_testing.domain.flakiness import (
    ExecutionSample,
    FlakinessConfig,
    SampleOutcome,
    flakiness_score,
)
from radius_testing.dto.commands import (
    DiscoverTestsCommand,
    ExecuteTestRunCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)
from radius_testing.dto.responses import (
    FlakyTestResponse,
    FlakyTestsResponse,
    SelectedTestAttributionResponse,
    TestCaseResponse,
    TestDiscoveryResponse,
    TestIngestionResponse,
    TestRunPlanResponse,
    TestRunResultResponse,
    TestSelectionResponse,
    TestUploadResponse,
)
from radius_testing.infrastructure.junit_parser import JUnitReportParser
from radius_testing.infrastructure.result_matching import (
    attribute_selected_tests,
    report_cases,
)
from radius_testing.interfaces.discovery import TestDiscoverer
from radius_testing.interfaces.runner import TestCommandPlanner, TestRunner
from radius_testing.interfaces.selection import TestSelector
from radius_testing.interfaces.store import TestStore


class TestingApplicationService:
    """Coordinates deterministic test discovery, selection, and planning."""

    def __init__(
        self,
        discoverer: TestDiscoverer,
        selector: TestSelector,
        store: TestStore,
        planner: TestCommandPlanner,
        runner: TestRunner | None = None,
        parser: JUnitReportParser | None = None,
    ) -> None:
        self._discoverer = discoverer
        self._selector = selector
        self._store = store
        self._planner = planner
        self._runner = runner
        self._parser = parser or JUnitReportParser()


    def discover_tests(
        self,
        command: DiscoverTestsCommand,
    ) -> TestDiscoveryResponse:
        """Discover and store test cases."""

        tests = self.discover_test_cases(command)
        return TestDiscoveryResponse(
            test_count=len(tests),
            tests=tuple(TestCaseResponse.from_entity(test) for test in tests),
        )

    def discover_test_cases(self, command: DiscoverTestsCommand) -> tuple:
        """Discover, persist, and return the test cases of one snapshot."""

        if not command.repository_path.exists() or not command.repository_path.is_dir():
            msg = f"Repository path does not exist: {command.repository_path}."
            raise ValidationError(msg)
        discovered = self._discoverer.discover(command.repository_path)
        if command.repository_id is not None:
            # Test ids are derived from the path; include the repository so two
            # repositories with the same test path never share a row.
            discovered = tuple(
                replace(
                    test,
                    id=uuid5(
                        NAMESPACE_URL,
                        f"radius:test:{command.repository_id}:{test.path.value}",
                    ),
                )
                for test in discovered
            )
        self._store.save_test_cases(discovered, command.repository_id)
        return discovered

    def select_tests(self, command: SelectTestsCommand) -> TestSelectionResponse:
        """Select tests for changed and affected paths."""

        tests = (
            command.available_tests
            if command.available_tests is not None
            else self._store.list_test_cases()
        )
        selection = self._selector.select(
            command.analysis_id,
            tests,
            command.changed_file_paths,
            command.affected_file_paths,
            command.changed_symbols,
            command.semantic_evidence,
            command.coverage_evidence,
            command.history_evidence,
            full_suite_reasons=command.full_suite_reasons,
            symbol_evidence=command.symbol_evidence,
        )
        return TestSelectionResponse.from_entity(
            self._store.save_selection(selection)
        )

    def plan_test_run(self, command: PlanTestRunCommand) -> TestRunPlanResponse:
        """Create a structured run plan from a saved selection."""

        selection = self._store.get_selection(command.analysis_id)
        if selection is None:
            msg = f"Test selection for analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)
        plan = self._planner.plan(
            command.analysis_id,
            tuple(selected.test_case for selected in selection.selected_tests),
        )
        return TestRunPlanResponse.from_entity(self._store.save_run_plan(plan))

    def get_selection(self, analysis_id) -> TestSelectionResponse:
        """Return saved test selection."""

        selection = self._store.get_selection(analysis_id)
        if selection is None:
            msg = f"Test selection for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return TestSelectionResponse.from_entity(selection)

    def execute_test_run(
        self,
        command: ExecuteTestRunCommand,
    ) -> TestRunResultResponse:
        """Execute a saved test run plan and persist result."""

        if self._runner is None:
            msg = "Test runner is not configured."
            raise ValidationError(msg)
        plan = self._store.get_run_plan(command.analysis_id)
        if plan is None:
            msg = f"Test run plan for analysis {command.analysis_id} was not found."
            raise NotFoundError(msg)
        result = self._runner.run(plan, command.repository_path)
        return TestRunResultResponse.from_entity(self._store.save_run_result(result))

    def get_run_result(self, analysis_id) -> TestRunResultResponse:
        """Return saved test run result."""

        result = self._store.get_run_result(analysis_id)
        if result is None:
            msg = f"Test run result for analysis {analysis_id} was not found."
            raise NotFoundError(msg)
        return TestRunResultResponse.from_entity(result)

    def get_test_history(self, analysis_id: UUID):
        """Return test execution history for an analysis."""
        return self._store.get_test_history(analysis_id)

    def get_test_statistics(self, analysis_id: UUID):
        """Return test execution statistics for an analysis."""
        return self._store.get_test_statistics(analysis_id)

    def list_flaky_tests(
        self,
        repository_id: UUID,
        config: FlakinessConfig | None = None,
    ) -> FlakyTestsResponse:
        """Score every test of a repository from its history; list the quarantined.

        Deterministic: history rows arrive in a stable (timestamp, id) order and
        the score is a pure function of them. The code key is the commit sha,
        so only reruns of the same commit count as comparable observations.
        """

        cfg = config or FlakinessConfig()
        by_test: dict[str, list[dict]] = {}
        for row in self._store.list_test_samples(repository_id):
            by_test.setdefault(row["test_path"], []).append(row)
        quarantined: list[FlakyTestResponse] = []
        insufficient = 0
        for path in sorted(by_test):
            rows = by_test[path]
            samples = tuple(
                ExecutionSample(SampleOutcome(row["status"]), row.get("commit_sha"))
                for row in rows
                if row["status"] in {item.value for item in SampleOutcome}
            )
            assessment = flakiness_score(samples, cfg)
            if assessment.score is None:
                insufficient += 1
            if assessment.quarantined:
                quarantined.append(
                    FlakyTestResponse(
                        test_path=path,
                        test_name=rows[-1]["test_name"],
                        score=assessment.score,
                        comparable=assessment.comparable,
                        flips=assessment.flips,
                        samples_considered=assessment.samples_considered,
                        quarantined=True,
                        last_status=rows[-1]["status"],
                    )
                )
        quarantined.sort(key=lambda item: (-(item.score or 0.0), item.test_path))
        return FlakyTestsResponse(
            repository_id=repository_id,
            window=cfg.window,
            min_comparable=cfg.min_comparable,
            threshold=cfg.threshold,
            quarantined=tuple(quarantined),
            insufficient_history_count=insufficient,
        )

    def get_recent_executions(
        self, repository_id: UUID | None = None, limit: int = 50
    ):
        """Return recent test executions across analyses."""
        return self._store.get_recent_executions(repository_id, limit)
    def ingest_test_results(
        self,
        analysis_id: UUID,
        content: str | bytes,
        commit_sha: str = "",
    ) -> TestRunResultResponse:
        """Ingest one CI / JUnit report and return the aggregate over all uploads."""

        aggregate, _ = self._ingest(analysis_id, content, commit_sha)
        return TestRunResultResponse.from_entity(aggregate)

    def count_result_uploads(self, analysis_id: UUID) -> int:
        """Return how many distinct result uploads an analysis has."""

        return len(self._store.list_result_uploads(analysis_id))

    def ingest_test_report(
        self,
        analysis_id: UUID,
        content: str | bytes,
        commit_sha: str,
    ) -> TestIngestionResponse:
        """Ingest one CI report and attribute the accumulated results.

        Uploads accumulate per analysis: failures are sticky across uploads,
        executed cases are unioned when matching selected tests, and an exact
        replay (same body hash) is recognised and not double-counted.
        Malformed reports raise ``ValidationError`` before anything is stored.
        """

        return self._ingest(analysis_id, content, commit_sha)[1]

    def _ingest(
        self,
        analysis_id: UUID,
        content: str | bytes,
        commit_sha: str,
    ) -> tuple[TestRunResult, TestIngestionResponse]:
        parsed = self._parser.parse(content, analysis_id)
        # Lock before reading/writing uploads so concurrent shards are
        # aggregated one after another, never from partial views.
        self._store.lock_result_uploads(analysis_id)
        body = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(body).hexdigest()
        upload = self._store.get_result_upload(analysis_id, digest)
        duplicate = upload is not None
        if upload is None:
            candidate = TestResultUpload(
                id=parsed.id,
                analysis_id=analysis_id,
                commit_sha=commit_sha.strip().lower(),
                body_sha256=digest,
                result=parsed,
                cases=report_cases(content),
            )
            upload = self._store.save_result_upload(candidate)
            duplicate = upload.id != candidate.id  # lost a concurrent replay race

        uploads = self._store.list_result_uploads(analysis_id)
        aggregate = aggregate_uploads(analysis_id, uploads)
        self._store.save_run_result(aggregate)
        cases = tuple(case for item in uploads for case in item.cases)

        selection = self._store.get_selection(analysis_id)
        attribution = None
        if selection is not None:
            attribution = attribute_selected_tests(
                tuple(item.test_case.path.value for item in selection.selected_tests),
                cases,
            )

        response = TestIngestionResponse(
            id=aggregate.id,
            analysis_id=analysis_id,
            status=aggregate.status.value,
            total_tests=aggregate.total_tests,
            passed=aggregate.passed,
            failed=aggregate.failed,
            skipped=aggregate.skipped,
            duration_ms=aggregate.duration_ms,
            coverage_percent=aggregate.coverage_percent,
            output=aggregate.output,
            upload_count=len(uploads),
            upload=TestUploadResponse(
                id=upload.id,
                commit_sha=upload.commit_sha,
                body_sha256=upload.body_sha256,
                duplicate=duplicate,
                status=upload.result.status.value,
                total_tests=upload.result.total_tests,
                passed=upload.result.passed,
                failed=upload.result.failed,
                skipped=upload.result.skipped,
                reported_cases=len(upload.cases),
            ),
            selected_tests=(
                SelectedTestAttributionResponse(
                    selected_count=len(attribution.selected),
                    executed_count=len(attribution.executed),
                    passed_count=len(attribution.passed),
                    failed_count=len(attribution.failed),
                    skipped_count=len(attribution.skipped),
                    not_reported_count=len(attribution.not_reported),
                    executed=attribution.executed,
                    failed=attribution.failed,
                    skipped=attribution.skipped,
                    not_reported=attribution.not_reported,
                )
                if attribution is not None
                else None
            ),
            contradictory_cases=contradictory_cases(cases),
        )
        return aggregate, response


def aggregate_uploads(
    analysis_id: UUID,
    uploads: tuple[TestResultUpload, ...],
) -> TestRunResult:
    """Combine distinct uploads into the run summary the verdict uses.

    Counts are summed per distinct upload. A failure anywhere is sticky: the
    aggregate is failed if any upload failed or any case was ever reported as
    failed, even when a later upload reports the same case as passing.
    """

    results = [upload.result for upload in uploads]
    failed_keys = {
        case.key
        for upload in uploads
        for case in upload.cases
        if case.outcome == CaseOutcome.FAILED
    }
    failed = max(sum(result.failed for result in results), len(failed_keys))
    if any(result.status == TestRunStatus.ERROR for result in results):
        status = TestRunStatus.ERROR
    elif failed > 0 or any(result.status == TestRunStatus.FAILED for result in results):
        status = TestRunStatus.FAILED
        failed = max(failed, 1)
    else:
        status = TestRunStatus.PASSED
    coverages = [
        result.coverage_percent for result in results if result.coverage_percent is not None
    ]
    return TestRunResult(
        id=uuid4(),
        analysis_id=analysis_id,
        status=status,
        total_tests=sum(result.total_tests for result in results),
        passed=sum(result.passed for result in results),
        failed=failed,
        skipped=sum(result.skipped for result in results),
        duration_ms=sum(result.duration_ms for result in results),
        # Shard coverage is not additive; report the most conservative value.
        coverage_percent=min(coverages) if coverages else None,
        output="\n\n".join(result.output for result in results if result.output),
    )


def contradictory_cases(cases: tuple[ReportedTestCase, ...]) -> tuple[str, ...]:
    """Return cases reported as passed in one place and failed in another."""

    outcomes: dict[tuple[str, str, str], set[str]] = {}
    for case in cases:
        outcomes.setdefault(case.key, set()).add(case.outcome)
    return tuple(
        "::".join(part for part in key if part)
        for key, seen in outcomes.items()
        if {CaseOutcome.PASSED, CaseOutcome.FAILED} <= seen
    )
