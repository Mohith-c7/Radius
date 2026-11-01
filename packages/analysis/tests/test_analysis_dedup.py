"""Duplicate analysis suppression for the same PR head commit."""

from uuid import uuid4

from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import RerunAnalysisCommand, StartAnalysisCommand
from radius_analysis.infrastructure import InMemoryAnalysisStore


class _Pipeline:
    def __init__(self) -> None:
        self.enqueued: list = []

    def enqueue(self, analysis_id) -> None:
        self.enqueued.append(analysis_id)


def _service():
    pipeline = _Pipeline()
    return AnalysisApplicationService(InMemoryAnalysisStore(), pipeline=pipeline), pipeline


def _command(pull_request_id, sha="a" * 40):
    return StartAnalysisCommand(
        repository_id=uuid4(),
        pull_request_id=pull_request_id,
        commit_sha=sha,
    )


def test_duplicate_start_reuses_active_analysis_and_enqueues_once() -> None:
    service, pipeline = _service()
    pr = uuid4()

    first = service.start_analysis(_command(pr))
    second = service.start_analysis(_command(pr))

    assert first.id == second.id
    assert pipeline.enqueued == [first.id]


def test_running_analysis_also_blocks_duplicates() -> None:
    service, pipeline = _service()
    pr = uuid4()
    first = service.start_analysis(_command(pr))
    service.mark_running(first.id)

    assert service.start_analysis(_command(pr)).id == first.id
    assert len(pipeline.enqueued) == 1


def test_terminal_analysis_does_not_block_new_start() -> None:
    service, pipeline = _service()
    pr = uuid4()
    first = service.start_analysis(_command(pr))
    service.mark_running(first.id)
    service.complete_analysis(first.id)

    second = service.start_analysis(_command(pr))

    assert second.id != first.id
    assert len(pipeline.enqueued) == 2


def test_different_head_sha_creates_new_analysis() -> None:
    service, _ = _service()
    pr = uuid4()

    first = service.start_analysis(_command(pr, "a" * 40))
    second = service.start_analysis(_command(pr, "b" * 40))

    assert first.id != second.id


def test_rerun_always_creates_new_analysis() -> None:
    service, pipeline = _service()
    first = service.start_analysis(_command(uuid4()))

    rerun = service.rerun_analysis(RerunAnalysisCommand(analysis_id=first.id))

    assert rerun.id != first.id
    assert len(pipeline.enqueued) == 2
