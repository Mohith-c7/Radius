"""End-to-end validation for the deterministic Phase 1 backend spine."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, BlastRadius, ChangedFile
from radius_analysis.dto import (
    AnalyzeDiffCommand,
    ComputeBlastRadiusCommand,
    StartAnalysisCommand,
)
from radius_analysis.infrastructure import UnifiedDiffChangeAnalyzer
from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import (
    AnalysisEvidence,
    CoveragePercent,
    ImpactEvidence,
)
from radius_confidence.domain import (
    TestEvidence as ConfidenceTestEvidence,
)
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    InMemoryConfidenceStore,
)
from radius_graph.application import GraphApplicationService
from radius_graph.dto import BuildGraphCommand
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.domain import (
    FileChecksum,
    ImportReference,
    ParsedSourceFile,
    RepositoryParseResult,
    SourceFile,
    SourceLanguage,
    SourceLocation,
    SourcePath,
    Symbol,
    SymbolName,
    SymbolType,
    SymbolVisibility,
)
from radius_testing.application import TestingApplicationService as RadiusTestingService
from radius_testing.dto import (
    DiscoverTestsCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)


class InMemoryAnalysisStore:
    """Small cross-package fake for analysis state."""

    def __init__(self) -> None:
        self.analyses: dict[UUID, Analysis] = {}

    def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        return self.analyses.get(analysis_id)

    def list(
        self,
        repository_id: UUID | None = None,
        pull_request_id: UUID | None = None,
        status: AnalysisStatus | None = None,
    ) -> list[Analysis]:
        return list(self.analyses.values())

    def save(self, analysis: Analysis) -> Analysis:
        analysis.id = analysis.id or uuid4()
        self.analyses[analysis.id] = analysis
        return analysis

    def update_status(self, analysis_id: UUID, status: AnalysisStatus) -> Analysis:
        analysis = self.analyses[analysis_id]
        analysis.status = status
        return analysis

    def replace_changed_files(
        self,
        analysis_id: UUID,
        changed_files: list[ChangedFile],
    ) -> list[ChangedFile]:
        saved = [
            ChangedFile(
                id=changed_file.id or uuid4(),
                analysis_id=analysis_id,
                path=changed_file.path,
                change_type=changed_file.change_type,
                additions=changed_file.additions,
                deletions=changed_file.deletions,
            )
            for changed_file in changed_files
        ]
        self.analyses[analysis_id].changed_files = saved
        return saved

    def save_blast_radius(self, blast_radius: BlastRadius) -> BlastRadius:
        saved = BlastRadius(
            id=blast_radius.id or uuid4(),
            analysis_id=blast_radius.analysis_id,
            affected_files=blast_radius.affected_files,
            affected_symbols=blast_radius.affected_symbols,
            affected_modules=blast_radius.affected_modules,
            affected_tests=blast_radius.affected_tests,
            dependency_depth=blast_radius.dependency_depth,
        )
        self.analyses[blast_radius.analysis_id].blast_radius = saved
        return saved

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        return self.analyses[analysis_id].blast_radius


def test_phase1_backend_spine_from_diff_to_confidence(tmp_path: Path) -> None:
    repository_id = uuid4()
    pull_request_id = uuid4()
    analysis_service = AnalysisApplicationService(
        InMemoryAnalysisStore(),
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    analysis = analysis_service.start_analysis(
        StartAnalysisCommand(
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            commit_sha="a" * 40,
        )
    )

    changed = analysis_service.analyze_diff(
        AnalyzeDiffCommand(
            analysis_id=analysis.id,
            diff_text="""diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1 +1,2 @@
 value = 1
+updated = True
""",
        )
    )
    graph = _build_graph(repository_id, analysis.id)
    blast_radius = analysis_service.compute_blast_radius(
        ComputeBlastRadiusCommand(
            analysis_id=analysis.id,
            graph_snapshot=graph,
            changed_file_paths=tuple(item.path for item in changed.changed_files),
        )
    )

    testing = _testing_service()
    _write_test_files(tmp_path)
    testing.discover_tests(DiscoverTestsCommand(tmp_path))
    selection = testing.select_tests(
        SelectTestsCommand(
            analysis_id=analysis.id,
            changed_file_paths=tuple(item.path for item in changed.changed_files),
            affected_file_paths=("src/service.py", "src/api.py"),
        )
    )
    plan = testing.plan_test_run(PlanTestRunCommand(analysis.id))

    confidence = ConfidenceApplicationService(
        scorer=DeterministicConfidenceScorer(),
        store=InMemoryConfidenceStore(),
    ).generate_report(
        GenerateConfidenceReportCommand(
            analysis_id=analysis.id,
            impact=ImpactEvidence(
                affected_files=blast_radius.affected_files,
                affected_symbols=blast_radius.affected_symbols,
                affected_modules=blast_radius.affected_modules,
                affected_tests=selection.selected_count,
                dependency_depth=blast_radius.dependency_depth,
            ),
            tests=ConfidenceTestEvidence(
                total_tests=selection.selected_count,
                passed=selection.selected_count,
                failed=0,
                skipped=0,
                coverage_percent=CoveragePercent(88),
            ),
            analysis=AnalysisEvidence(changed_files=1, covered_files=("src/app.py",)),
        )
    )

    assert [item.path for item in changed.changed_files] == ["src/core.py"]
    assert blast_radius.affected_files == 3
    assert blast_radius.dependency_depth == 2
    assert selection.selected_count == 3
    assert plan.command_plan == (
        (
            "python",
            (
                "-m",
                "pytest",
                "tests/test_api.py",
                "tests/test_core.py",
                "tests/test_service.py",
            ),
        ),
    )
    assert confidence.confidence_score == 100
    assert confidence.risk_level == "low"


def _build_graph(repository_id: UUID, analysis_id: UUID):
    source_files = (
        _source_file("src/core.py"),
        _source_file("src/service.py"),
        _source_file("src/api.py"),
    )
    parsed_files = (
        _parsed(source_files[0], "core"),
        _parsed(source_files[1], "service", imports=("src.core",)),
        _parsed(source_files[2], "api", imports=("src.service",)),
    )
    parse_result = RepositoryParseResult(
        repository_path=Path("repo"),
        source_files=source_files,
        parsed_files=parsed_files,
    )
    store = InMemoryGraphStore()
    GraphApplicationService(store).build_graph(
        BuildGraphCommand(
            repository_id=repository_id,
            analysis_id=analysis_id,
            parse_result=parse_result,
        )
    )
    snapshot = store.get_snapshot(analysis_id)
    assert snapshot is not None
    return snapshot


def _source_file(path: str) -> SourceFile:
    return SourceFile(
        path=SourcePath(path),
        language=SourceLanguage.PYTHON,
        checksum=FileChecksum("a" * 64),
    )


def _parsed(
    source_file: SourceFile,
    symbol_name: str,
    imports: tuple[str, ...] = (),
) -> ParsedSourceFile:
    return ParsedSourceFile(
        source_file=source_file,
        symbols=(
            Symbol(
                name=SymbolName(symbol_name),
                symbol_type=SymbolType.FUNCTION,
                visibility=SymbolVisibility.PUBLIC,
                location=SourceLocation(start_line=1),
            ),
        ),
        imports=tuple(ImportReference(source=item) for item in imports),
    )


def _testing_service() -> RadiusTestingService:
    return RadiusTestingService(
        discoverer=ConventionalTestDiscoverer(),
        selector=PathBasedTestSelector(),
        store=InMemoryTestStore(),
        planner=StaticTestCommandPlanner(),
    )


def _write_test_files(root: Path) -> None:
    tests_dir = root / "tests"
    tests_dir.mkdir()
    for name in ("test_core.py", "test_service.py", "test_api.py"):
        (tests_dir / name).write_text("def test_placeholder(): pass\n")
