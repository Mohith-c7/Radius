"""Analysis domain tests."""

from uuid import uuid4

import pytest
from radius_analysis.domain import (
    Analysis,
    AnalysisStatus,
    BlastRadius,
    ChangedFile,
    ChangedFileType,
    CommitSha,
    FilePath,
)


def test_commit_sha_and_file_path_validation() -> None:
    with pytest.raises(ValueError, match="Commit SHA cannot be empty"):
        CommitSha("")

    with pytest.raises(ValueError, match="Commit SHA cannot exceed"):
        CommitSha("a" * 41)

    with pytest.raises(ValueError, match="File path must be repository-relative"):
        FilePath("/src/app.py")


def test_analysis_lifecycle_transitions() -> None:
    analysis = _analysis()

    analysis.mark_running()
    analysis.complete()

    assert analysis.status == AnalysisStatus.COMPLETED
    assert analysis.completed_at is not None


def test_completed_analysis_cannot_be_cancelled() -> None:
    analysis = _analysis()
    analysis.complete()

    with pytest.raises(ValueError, match="Completed analyses cannot be cancelled"):
        analysis.cancel()


def test_changed_file_and_blast_radius_reject_negative_counts() -> None:
    with pytest.raises(ValueError, match="additions cannot be negative"):
        ChangedFile(
            id=None,
            analysis_id=uuid4(),
            path=FilePath("src/app.py"),
            change_type=ChangedFileType.MODIFIED,
            additions=-1,
        )

    with pytest.raises(ValueError, match="dependency_depth cannot be negative"):
        BlastRadius(analysis_id=uuid4(), dependency_depth=-1, id=None)


def _analysis() -> Analysis:
    return Analysis(
        id=None,
        repository_id=uuid4(),
        pull_request_id=uuid4(),
        commit_sha=CommitSha("a" * 40),
    )
