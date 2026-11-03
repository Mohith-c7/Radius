"""C-18: worker job settings are bounded and validated."""

import pytest
from pydantic import ValidationError
from radius_worker.config import WorkerSettings


@pytest.mark.parametrize(
    "env",
    [
        {"WORKER_JOB_MAX_ATTEMPTS": 0},
        {"WORKER_JOB_MAX_ATTEMPTS": -1},
        {"WORKER_JOB_MAX_ATTEMPTS": 1000},
        {"WORKER_JOB_STALE_AFTER_SECONDS": 0},
        {"WORKER_JOB_STALE_AFTER_SECONDS": -5},
        {"WORKER_JOB_STALE_AFTER_SECONDS": 10},
        {"WORKER_ANALYSIS_DEADLINE_SECONDS": 0},
        {"WORKER_POLL_INTERVAL_SECONDS": 0},
        {"WORKER_POLL_INTERVAL_SECONDS": -1},
        {"WORKER_JOB_RETRY_BASE_SECONDS": -1},
        {"WORKER_HEARTBEAT_INTERVAL_SECONDS": 0},
        # heartbeat slower than half the stale window would let healthy jobs be recovered
        {"WORKER_JOB_STALE_AFTER_SECONDS": 100, "WORKER_HEARTBEAT_INTERVAL_SECONDS": 90},
        # deadline must exceed the stale window
        {"WORKER_JOB_STALE_AFTER_SECONDS": 3600, "WORKER_ANALYSIS_DEADLINE_SECONDS": 3600},
    ],
)
def test_out_of_range_values_are_rejected_with_a_clear_error(env) -> None:
    with pytest.raises(ValidationError) as excinfo:
        WorkerSettings(**env)
    assert "WORKER_" in str(excinfo.value) or "greater than" in str(excinfo.value)


def test_defaults_are_valid_and_heartbeat_is_derived_from_the_stale_window() -> None:
    settings = WorkerSettings()
    assert settings.job_max_attempts == 3
    assert settings.heartbeat_interval == 60.0
    assert WorkerSettings(WORKER_JOB_STALE_AFTER_SECONDS=60).heartbeat_interval == 20.0
    assert WorkerSettings(WORKER_HEARTBEAT_INTERVAL_SECONDS=5).heartbeat_interval == 5.0
    assert WorkerSettings(WORKER_JOB_RETRY_BASE_SECONDS=0).job_retry_base_seconds == 0
