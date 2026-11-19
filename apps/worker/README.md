# Radius Worker

Background processing application for long-running repository analysis, graph rebuilds, test execution, and report generation.

Jobs come from the durable SQL queue (`analysis_jobs`, `SqlAlchemyAnalysisJobQueue` in `packages/analysis`): the worker claims a job with a lease, heartbeats while it runs, retries with backoff and a reaper fails analyses past their deadline (`runner.py`); `maintenance.py` holds the opt-in retention purge. The same process runs the optional GitHub pull-request poller (`poller.py`) and the Verdict v2 republish outbox (`verdict_v2/`). Test execution is off by default (`WORKER_TEST_EXECUTION_MODE=disabled`). Container health: `python -m radius_worker.healthcheck`. Settings: [docs/operations/CONFIGURATION.md](../../docs/operations/CONFIGURATION.md).
