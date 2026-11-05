"""Acceptance: one analysis yields correlated logs and a single trace.

Drives a signed webhook through the API, the SQL job queue and the worker
(including the publish step) with an in-memory span exporter, then checks that
every span shares one trace id and every log line carries the correlation ids.
"""

import hashlib
import hmac
import io
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base
from radius_shared.database.models import AnalysisJob, Organization
from radius_shared.logging import JsonFormatter, RedactingFilter
from radius_shared.observability import configure_tracing, reset_tracing
from radius_worker import runner as runner_module
from radius_worker.config import WorkerSettings
from radius_worker.runner import create_sql_worker_runtime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytest.importorskip("opentelemetry.sdk")


def test_one_analysis_produces_one_trace_and_correlated_logs(
    tmp_path: Path, monkeypatch
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    source_repo = _create_git_repository(tmp_path / "source")
    head_sha = _git(("rev-parse", "HEAD"), cwd=source_repo)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    organization_id = uuid4()
    _create_database(database_url, organization_id)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(organization_id))
    monkeypatch.setenv("GITHUB_SINGLE_TENANT", "true")
    monkeypatch.setenv("REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    get_api_settings.cache_clear()

    # Make the publish step run against a fake publisher so its span exists.
    published = []

    class FakePublisher:
        def __init__(self, _client) -> None:
            pass

        def publish(self, *, installation_id, report) -> None:
            published.append(installation_id)

    monkeypatch.setattr(runner_module, "GitHubAnalysisPublisher", FakePublisher)
    monkeypatch.setattr(
        runner_module, "_github_settings", lambda _s: SimpleNamespace(enabled=True)
    )
    monkeypatch.setattr(runner_module, "_github_installation_id", lambda **_: 1)
    monkeypatch.setattr(runner_module, "_github_clone_headers", lambda **_: ())
    monkeypatch.setattr(
        runner_module,
        "_github_report",
        lambda *_: SimpleNamespace(pull_request_number=5),
    )

    exporter = InMemorySpanExporter()
    assert configure_tracing(span_exporter=exporter)
    log_stream = io.StringIO()
    root = logging.getLogger()
    previous_level = root.level
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    try:
        # create_app() resets root logging handlers, so attach ours afterwards.
        client = TestClient(create_app())
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        body = _webhook_body(source_repo, head_sha)
        response = client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers=_github_headers(body, "delivery-obs", "secret"),
        )
        assert response.status_code == 202
        analysis_id = response.json()["data"]["analysisId"]

        # Simulate a separate worker process: nothing in-process may carry the
        # trace, only analysis_jobs.traceparent.
        engine = create_engine(database_url)
        with Session(engine) as check:
            stored = check.scalar(select(AnalysisJob.traceparent))
        engine.dispose()
        assert stored is not None

        runtime = create_sql_worker_runtime(WorkerSettings())
        runtime.git_client = _LocalSourceGit(source_repo)
        assert runtime.run_once() is True
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        reset_tracing()

    assert published == [1]

    spans = exporter.get_finished_spans()
    names = {item.name for item in spans}
    assert {
        "http.request",
        "webhook.handle",
        "queue.enqueue",
        "worker.job",
        "stage.analyze_changes",
        "stage.parse",
        "stage.build_graph",
        "stage.confidence",
        "stage.publish",
    } <= names
    assert len({item.context.trace_id for item in spans}) == 1
    assert stored.split("-")[1] == format(spans[0].context.trace_id, "032x")

    by_name = {item.name: item for item in spans}
    http_span = by_name["http.request"]
    assert http_span.parent is None
    assert by_name["worker.job"].parent.span_id == by_name["queue.enqueue"].context.span_id
    assert by_name["stage.parse"].parent.span_id == by_name["worker.job"].context.span_id
    assert by_name["worker.job"].attributes["radius.analysis_id"] == analysis_id
    assert by_name["webhook.handle"].attributes["radius.delivery_id"] == "delivery-obs"

    records = [json.loads(line) for line in log_stream.getvalue().splitlines()]
    worker_records = [r for r in records if r.get("analysis_id") == analysis_id]
    assert any(r["message"] == "Analysis completed" for r in worker_records)
    # The queue's "claimed" line is logged before the job context is bound.
    in_job = [r for r in worker_records if r["message"] != "Analysis job claimed"]
    assert in_job
    for record in in_job:
        assert record["job_id"]
        assert record["organization_id"] == str(organization_id)
    api_record = next(r for r in records if r["message"] == "Webhook delivery handled")
    assert api_record["delivery_id"] == "delivery-obs"
    assert api_record["organization_id"] == str(organization_id)
    assert api_record["request_id"]
    trace_ids = {r["trace_id"] for r in records if "trace_id" in r}
    assert trace_ids == {format(http_span.context.trace_id, "032x")}


# Helpers copied from test_persisted_webhook_flow.py (tests are not importable
# across directories in the full-suite run).
def _create_database(database_url: str, organization_id) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organization(id=organization_id, name="Acme"))
        session.commit()


def _webhook_body(source_repo: Path, head_sha: str) -> bytes:
    payload = {
        "action": "synchronize",
        "repository": {
            "id": 12345,
            "name": "radius",
            "private": True,
            "default_branch": "main",
            "clone_url": "https://github.com/acme/radius.git",
            "owner": {"login": "acme"},
        },
        "pull_request": {
            "number": 5,
            "title": "Change core",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "octocat"},
            "head": {"ref": "feature", "sha": head_sha},
            "base": {"ref": "main", "sha": "0" * 40},
            "created_at": "2026-07-29T10:00:00Z",
            "merged_at": None,
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _github_headers(body: bytes, delivery_id: str, secret: str) -> dict[str, str]:
    signature = (
        "sha256="
        + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }


def _create_git_repository(path: Path) -> Path:
    path.mkdir()
    _git(("init", "-b", "main"), cwd=path)
    _git(("config", "user.email", "radius@example.com"), cwd=path)
    _git(("config", "user.name", "Radius"), cwd=path)
    _write_repository(path, return_value=1)
    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "initial"), cwd=path)
    _git(("checkout", "-b", "feature"), cwd=path)
    _write_repository(path, return_value=2)
    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "feature"), cwd=path)
    return path


def _write_repository(root: Path, *, return_value: int) -> None:
    (root / "src").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "src" / "core.py").write_text(
        f"def calculate():\n    return {return_value}\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_core.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )


def _git(args: tuple[str, ...], *, cwd: Path) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class _LocalSourceGit:
    """Test double: serves any clone request from a local source repository.

    Production git clients refuse local paths and file:// (A-01/A-02), so the
    end-to-end flows point the runtime at this double instead.
    """

    def __init__(self, source: Path) -> None:
        self._source = source

    def clone_or_fetch(self, clone_url, destination, *, extra_headers=()):
        import subprocess

        if destination.exists():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ("git", "clone", "-q", str(self._source), str(destination)),
            check=True,
            capture_output=True,
        )
        return destination

    def checkout(self, repository_path, branch_name):
        from radius_repository.infrastructure import LocalGitRepositoryClient

        LocalGitRepositoryClient().checkout(repository_path, branch_name)
