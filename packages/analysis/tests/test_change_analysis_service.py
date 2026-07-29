"""Change analysis service integration tests."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, BlastRadius, ChangedFile
from radius_analysis.dto import (
    AnalyzeDiffCommand,
    AnalyzeRepositoryDiffCommand,
    StartAnalysisCommand,
)
from radius_analysis.infrastructure import UnifiedDiffChangeAnalyzer


class InMemoryAnalysisStore:
    """Small fake used to exercise change-analysis service behavior."""

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

    def update_status(
        self,
        analysis_id: UUID,
        status: AnalysisStatus,
    ) -> Analysis:
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
        self.analyses[blast_radius.analysis_id].blast_radius = blast_radius
        return blast_radius

    def get_blast_radius(self, analysis_id: UUID) -> BlastRadius | None:
        return self.analyses[analysis_id].blast_radius


class FakeDiffProvider:
    """Returns a fixed diff text."""

    def __init__(self, diff_text: str) -> None:
        self.diff_text = diff_text
        self.calls: list[tuple[Path, str, str]] = []

    def get_diff(self, repository_path: Path, base_ref: str, head_ref: str) -> str:
        self.calls.append((repository_path, base_ref, head_ref))
        return self.diff_text


def test_analyze_diff_records_parsed_changed_files() -> None:
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(
        store,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
    )
    analysis = service.start_analysis(_start_command())

    response = service.analyze_diff(
        AnalyzeDiffCommand(
            analysis_id=analysis.id,
            diff_text="""diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old
+new
""",
        )
    )

    assert response.analysis_id == analysis.id
    assert response.changed_files[0].path == "src/app.py"
    assert service.get_analysis(analysis.id).changed_files[0].change_type == "modified"


def test_analyze_repository_diff_uses_provider_and_records_changes() -> None:
    provider = FakeDiffProvider(
        """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -0,0 +1 @@
+new
"""
    )
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(
        store,
        change_analyzer=UnifiedDiffChangeAnalyzer(),
        diff_provider=provider,
    )
    analysis = service.start_analysis(_start_command())

    response = service.analyze_repository_diff(
        AnalyzeRepositoryDiffCommand(
            analysis_id=analysis.id,
            repository_path=".",
            base_ref="main",
            head_ref="HEAD",
        )
    )

    assert provider.calls == [(Path("."), "main", "HEAD")]
    assert response.changed_files[0].additions == 1


def _start_command() -> StartAnalysisCommand:
    return StartAnalysisCommand(
        repository_id=uuid4(),
        pull_request_id=uuid4(),
        commit_sha="a" * 40,
    )
