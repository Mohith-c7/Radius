"""Change analysis service integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.domain import Analysis, AnalysisStatus, BlastRadius, ChangedFile
from radius_analysis.dto import (
    AnalyzeDiffCommand,
    AnalyzeRepositoryDiffCommand,
    StartAnalysisCommand,
)
from radius_analysis.infrastructure import UnifiedDiffChangeAnalyzer
from radius_analysis.infrastructure.git_diff_provider import SubprocessGitDiffProvider
from radius_shared.errors import ValidationError


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

    def __init__(self, diff_text: str | list[str], *, parent_ref: str | None = "head-parent") -> None:
        self.diff_text = diff_text
        self.diff_texts = list(diff_text) if isinstance(diff_text, list) else None
        self.parent_ref = parent_ref
        self.calls: list[tuple[Path, str, str]] = []
        self.failure: Exception | None = None

    def get_diff(self, repository_path: Path, base_ref: str, head_ref: str) -> str:
        self.calls.append((repository_path, base_ref, head_ref))
        if self.failure is not None:
            raise self.failure
        if self.diff_texts is not None:
            return self.diff_texts.pop(0)
        return self.diff_text

    def get_parent_ref(self, repository_path: Path, head_ref: str) -> str | None:
        if head_ref == "invalid":
            raise ValueError("invalid head reference")
        return self.parent_ref


def _repo_diff(service, analysis_id, base="base", head="head"):
    return service.analyze_repository_diff(
        AnalyzeRepositoryDiffCommand(
            analysis_id=analysis_id,
            repository_path=".",
            base_ref=base,
            head_ref=head,
        )
    )


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


def test_equal_base_and_head_is_a_valid_empty_diff() -> None:
    provider = FakeDiffProvider("")
    store = InMemoryAnalysisStore()
    service = AnalysisApplicationService(store, diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    response = _repo_diff(service, analysis.id, base="head", head="head")
    assert response.changed_files == ()
    assert provider.calls == [(Path("."), "head", "head")]


def test_empty_working_tree_diff_is_valid_when_parent_diff_is_empty() -> None:
    provider = FakeDiffProvider("")
    service = AnalysisApplicationService(InMemoryAnalysisStore(), diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    assert _repo_diff(service, analysis.id).changed_files == ()
    assert provider.calls == [
        (Path("."), "base", "head"),
        (Path("."), "head-parent", "head"),
    ]


def test_empty_base_diff_uses_parent_commit_diff() -> None:
    provider = FakeDiffProvider(["", "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+x\n"])
    service = AnalysisApplicationService(InMemoryAnalysisStore(), change_analyzer=UnifiedDiffChangeAnalyzer(), diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    result = _repo_diff(service, analysis.id)
    assert result.changed_files[0].path == "a.py"
    assert provider.calls[-1][1:] == ("head-parent", "head")


def test_root_commit_has_a_valid_empty_parent_fallback() -> None:
    provider = FakeDiffProvider("", parent_ref=None)
    service = AnalysisApplicationService(InMemoryAnalysisStore(), diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    assert _repo_diff(service, analysis.id).changed_files == ()


def test_invalid_head_reference_is_not_reported_as_empty() -> None:
    provider = FakeDiffProvider("")
    service = AnalysisApplicationService(InMemoryAnalysisStore(), diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    import pytest

    with pytest.raises(ValueError, match="invalid head"):
        _repo_diff(service, analysis.id, head="invalid")


def test_git_provider_failure_is_not_reported_as_empty() -> None:
    provider = FakeDiffProvider("")
    provider.failure = RuntimeError("git unavailable")
    service = AnalysisApplicationService(InMemoryAnalysisStore(), diff_provider=provider)
    analysis = service.start_analysis(_start_command())
    import pytest

    with pytest.raises(RuntimeError, match="git unavailable"):
        _repo_diff(service, analysis.id)


def test_empty_diff_for_missing_analysis_remains_not_found() -> None:
    import pytest
    from radius_shared.errors import NotFoundError

    service = AnalysisApplicationService(InMemoryAnalysisStore(), diff_provider=FakeDiffProvider(""))
    with pytest.raises(NotFoundError):
        _repo_diff(service, uuid4(), base="head", head="head")


def test_git_provider_distinguishes_root_commit_from_invalid_head(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    commands = [
        ("git", "init", "-b", "main"),
        ("git", "config", "user.email", "test@example.com"),
        ("git", "config", "user.name", "Test"),
    ]
    for command in commands:
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
    (repository / "file.txt").write_text("root\n", encoding="utf-8")
    subprocess.run(("git", "add", "file.txt"), cwd=repository, check=True)
    subprocess.run(
        ("git", "commit", "-m", "root"), cwd=repository, check=True, capture_output=True
    )
    provider = SubprocessGitDiffProvider()

    assert provider.get_parent_ref(repository, "HEAD") is None
    with pytest.raises(ValidationError):
        provider.get_parent_ref(repository, "missing-head")
    with pytest.raises(ValidationError):
        provider.get_diff(repository, "main", "missing-head")


def _start_command() -> StartAnalysisCommand:
    return StartAnalysisCommand(
        repository_id=uuid4(),
        pull_request_id=uuid4(),
        commit_sha="a" * 40,
    )
