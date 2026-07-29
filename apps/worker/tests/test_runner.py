from uuid import uuid4

import pytest
from radius_worker.runner import run_worker, run_worker_once


def test_run_worker_reports_ready(capsys) -> None:
    run_worker()

    captured = capsys.readouterr()
    assert "Radius worker ready" in captured.out


def test_run_worker_once_claims_executes_and_completes_job() -> None:
    queue = FakeQueue()
    orchestrator = FakeOrchestrator()

    processed = run_worker_once(
        queue=queue,
        orchestrator=orchestrator,
        command_loader=lambda job: job.analysis_id,
    )

    assert processed is True
    assert orchestrator.executed == [queue.analysis_id]
    assert queue.completed == [queue.analysis_id]


def test_run_worker_once_marks_job_failed_on_error() -> None:
    queue = FakeQueue()
    orchestrator = FakeOrchestrator(should_fail=True)

    with pytest.raises(RuntimeError):
        run_worker_once(
            queue=queue,
            orchestrator=orchestrator,
            command_loader=lambda job: job.analysis_id,
        )

    assert queue.failed == [queue.analysis_id]


class FakeJob:
    def __init__(self, analysis_id):
        self.analysis_id = analysis_id


class FakeQueue:
    def __init__(self) -> None:
        self.analysis_id = uuid4()
        self.claimed = False
        self.completed = []
        self.failed = []

    def claim_next(self):
        if self.claimed:
            return None
        self.claimed = True
        return FakeJob(self.analysis_id)

    def complete(self, analysis_id) -> None:
        self.completed.append(analysis_id)

    def fail(self, analysis_id, error: str) -> None:
        self.failed.append(analysis_id)


class FakeOrchestrator:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.executed = []

    def execute(self, command) -> None:
        if self.should_fail:
            raise RuntimeError("failed")
        self.executed.append(command)
