"""Analysis application service tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, BlastRadius, ChangedFile
from radius_analysis.dto import (
    AnalysisListQuery,
    ChangedFileInput,
    RecordChangedFilesCommand,
    RerunAnalysisCommand,
    SaveBlastRadiusCommand,
    StartAnalysisCommand,
)
from radius_shared.errors import NotFoundError, ValidationError


class InMemoryAnalysisStore:
    """Small fake used to exercise service behavior."""

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
        analyses = list(self.analyses.values())
        if repository_id is not None:
            analyses = [
                analysis
                for analysis in analyses
                if analysis.repository_id == repository_id
            ]
        if pull_request_id is not None:
            analyses = [
                analysis
                for analysis in analyses
                if analysis.pull_request_id == pull_request_id
            ]
        if status is not None:
            analyses = [analysis for analysis in analyses if analysis.status == status]
        return analyses

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


class FakePipeline:
    """Captures enqueue requests."""

    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    def enqueue(self, analysis_id: UUID) -> None:
        self.enqueued.append(analysis_id)


def test_start_analysis_creates_pending_run_and_enqueues_pipeline() -> None:
    store = InMemoryAnalysisStore()
    pipeline = FakePipeline()
    service = AnalysisApplicationService(store, pipeline)

    response = service.start_analysis(_start_command())

    assert response.id in pipeline.enqueued
    assert response.status == "pending"
    assert response.changed_files == ()


def test_rerun_analysis_creates_new_analysis_without_mutating_existing() -> None:
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(store)
    original = service.start_analysis(_start_command())

    rerun = service.rerun_analysis(RerunAnalysisCommand(analysis_id=original.id))

    assert rerun.id != original.id
    assert service.get_analysis(original.id).status == "pending"


def test_list_analyses_filters_by_repository_and_status() -> None:
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(store)
    repository_id = uuid4()
    kept = service.start_analysis(_start_command(repository_id=repository_id))
    other = service.start_analysis(_start_command(repository_id=repository_id))
    service.cancel_analysis(other.id)

    result = service.list_analyses(
        AnalysisListQuery(repository_id=repository_id, status="pending")
    )

    assert [analysis.id for analysis in result] == [kept.id]


def test_record_changed_files_and_save_blast_radius() -> None:
    service = AnalysisApplicationService(InMemoryAnalysisStore())
    analysis = service.start_analysis(_start_command())

    changed_files = service.record_changed_files(
        RecordChangedFilesCommand(
            analysis_id=analysis.id,
            changed_files=(
                ChangedFileInput(
                    path="src/app.py",
                    change_type="modified",
                    additions=3,
                    deletions=1,
                ),
            ),
        )
    )
    blast_radius = service.save_blast_radius(
        SaveBlastRadiusCommand(
            analysis_id=analysis.id,
            affected_files=4,
            affected_symbols=2,
            affected_modules=1,
            affected_tests=5,
            dependency_depth=3,
        )
    )

    assert changed_files[0].path == "src/app.py"
    assert blast_radius.affected_tests == 5
    assert service.get_blast_radius(analysis.id).dependency_depth == 3


def test_missing_analysis_and_invalid_filters_raise_expected_errors() -> None:
    service = AnalysisApplicationService(InMemoryAnalysisStore())

    with pytest.raises(NotFoundError):
        service.get_analysis(uuid4())

    with pytest.raises(ValidationError):
        service.list_analyses(AnalysisListQuery(status="stuck"))


def _start_command(repository_id: UUID | None = None) -> StartAnalysisCommand:
    return StartAnalysisCommand(
        repository_id=repository_id or uuid4(),
        pull_request_id=uuid4(),
        commit_sha="a" * 40,
    )
